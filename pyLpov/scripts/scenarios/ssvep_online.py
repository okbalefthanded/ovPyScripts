from __future__ import print_function, division
from sklearn.metrics import confusion_matrix
from pyLpov.proc import processing
from pyLpov.machine_learning.cca import CCA 
import numpy as np
import pandas as pd
import pickle
import socket
import logging
import os

np.set_printoptions(precision=4)
OVTK_StimulationLabel_Base = 0x00008100

class SSVEPpredictor(OVBox):

    def __init__(self):
        super(SSVEPpredictor, self).__init__()
        self.experiment_mode = 'copy'
        self.signal = np.array([])
        self.channels = 0
        self.tmp_list = []
        self.n_trials = 0
        self.model = None
        self.model_path = None
        self.frequencies = ['idle', 14, 12, 10, 8]
        # self.frequencies = [14, 12, 10, 8]
        #
        self.ssvep_stims = []
        self.ssvep_stims_time = []
        self.ssvep_x = []
        self.ssvep_y = []
        self.low_pass = 4
        self.high_pass = 60
        self.filter_order = 2
        self.epoch_duration = 1.0
        self.ssvep_begin = 0
        self.ssvep_end = 0
        self.ssvep_correct = 0
        self.ssvep_target = []
        self.ssvep_pred = []
        #
        self.mode = 'sync'      
        self.harmonics = 0
        self.fs = 512
        self.samples = 0
        self.references = []
        #
        self.ends = 0
        self.nChunks = 0
        self.chunk = 0
        #
        self.command = None
        self.hostname = '127.0.0.1'
        self.feedback_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.feedback_port = 12345   
        self.do_feedback = False 
        self.trial_ended = False


    def initialize(self):
        #
        self.experiment_mode = self.setting["Experiment Mode"]
        self.fs = int(self.setting['Sample Rate'])
        self.epoch_duration = np.ceil(float(self.setting['Epoch Duration (in sec)']))
        self.low_pass = int(self.setting["Low Pass"])
        self.high_pass = int(self.setting["High Pass"])
        self.filter_order = int(self.setting["Filter Order"])
        self.harmonics = int(self.setting['Harmonics'])
        self.mode = self.setting["Mode"]
        self.model_path = self.setting["Classifier"]
        
        self.samples = int(self.epoch_duration * self.fs)
        t = np.arange(0.0, float(self.samples)) / self.fs
        if self.mode == 'sync':
            frequencies = self.frequencies[1:]
            self.frequencies = self.frequencies[1:]
            # generate reference signals
            x = [ [np.cos(2*np.pi*f*t*i),np.sin(2*np.pi*f*t*i)] for f in frequencies for i in range(1, self.harmonics+1)]
            self.references = np.array(x).reshape(len(frequencies), 2*self.harmonics, self.samples)
            self.ssvep_model = CCA(self.harmonics, frequencies, self.references, int(self.epoch_duration))
        elif self.mode == 'async':
            self.ssvep_model = pickle.load(open(self.ssvep_model_path, 'rb'),  encoding='latin1') #py3
            # self.ssvep_model = pickle.load(open(self.ssvep_model_path, 'rb')) #py2
            # generate reference by itcca method
            self.references = self.ssvep_model

    def stream_signal(self):
        '''
        '''
        signal_chunk = self.input[0].pop()

        if type(signal_chunk) == OVSignalHeader:
                self.channels, self.chunk = signal_chunk.dimensionSizes

        elif type(signal_chunk) == OVSignalBuffer:                                       
                tmp = [signal_chunk[i:i+self.chunk] for i in range(0, len(signal_chunk), self.chunk)]
                tmp = np.array(tmp)               
                self.signal = np.hstack((self.signal, tmp)) if self.signal.size else tmp                
                self.nChunks += 1                
                del tmp          
            
        del signal_chunk


    def filter_and_epoch(self, stim):
        '''
        '''
        self.ssvep_stims = np.array(self.ssvep_stims)                          
        self.ssvep_end = int(np.floor(stim.date * self.fs)) 
        self.ssvep_y = np.array(self.ssvep_y) 
        mrk = np.array(self.ssvep_stims_time).astype(int) - self.ssvep_begin
                   
        ssvep_signal = processing.eeg_filter(self.signal[:, self.ssvep_begin:self.ssvep_end].T, self.fs, self.low_pass, self.high_pass, self.filter_order)                            
        # print(f"signal shape: {ssvep_signal.shape}, Markers: {mrk}")
        ssvep_epochs = processing.eeg_epoch(ssvep_signal, np.array([0, self.samples],dtype=int), mrk)
        self.ssvep_x = ssvep_epochs.squeeze()
        # print(f"ssvep_x shape: {self.ssvep_x.shape}")
        del ssvep_signal
        del ssvep_epochs
        del mrk

    def predict(self):
        '''
        '''
        if self.mode == 'sync':                
            sync_trials = np.where(self.ssvep_y != 1)
            # ssvep_sync_epochs = ssvep_epochs[:,:,sync_trials].squeeze()
            ssvep_sync_epochs = self.ssvep_x
            # print(f"sync epochs shape: {ssvep_sync_epochs.shape}, samples {self.samples}")
            ssvep_predictions = self.ssvep_model.predict(ssvep_sync_epochs[0:self.samples,:].transpose((1,0))) + 1                                  
            ssvep_predictions = np.array(ssvep_predictions)                      
        elif self.mode == 'async':
            ssvep_predictions = self.ssvep_model.predict(self.ssvep_x)

        self.command = str(ssvep_predictions.item())

    def print_if_target(self):
        '''
        '''
        if self.experiment_mode == 'Copy':
            print('[SSVEP] preds:', self.command, ' target:', self.ssvep_y)
            if int(self.command) == self.ssvep_y:
                self.ssvep_correct += 1
            self.ssvep_target.append(self.ssvep_y[-1])

    def init_data(self):
        '''
        '''
        self.ssvep_x = []
        self.ssvep_y = []
        self.tmp_list = []
        self.ssvep_stims = []
        self.ssvep_stims_time = []                     
        self.n_trials += 1

    def print_results(self):
        '''
        '''        
        print('Trial N :', self.n_trials, ' / SSVEP Target : ', self.ssvep_target)
        print('Trial N :', self.n_trials, ' / SSVEP Pred : ', self.ssvep_pred)
        print('Trial N :', self.n_trials, ' / SSVEP Accuracy : ', (self.ssvep_correct / self.n_trials) * 100)

    def experiment_end(self):
        '''
        '''
        print('EXPERIMENT ENDS')
        print(' SSVEP Accuracy : ', (self.ssvep_correct / self.n_trials) * 100)                         
        self.switch = False
        del self.signal
        del self.ssvep_x
        del self.ssvep_model
        stimSet = OVStimulationSet(0.,0.)    
        stimSet.append(OVStimulation(OpenViBE_stimulation['OVTK_StimulationId_ExperimentStop'], 0.,0.)) 
        self.output[0].append(stimSet)     
       
    def process(self):
        
        # stream signal
        if self.input[0]:            
            self.stream_signal()        
        
        # collect Stimulations markers and times for each paradigm
        if self.input[1]:
            chunk = self.input[1].pop()
            if type(chunk) == OVStimulationSet:
                for stimIdx in range(len(chunk)):
                    if chunk:
                        stim = chunk.pop()               
                        # print('Received Marker: ', stim.identifier, 'stamped at', stim.date, 's')                        
                        # SSVEP session                        
                        if(stim.identifier == OpenViBE_stimulation['OVTK_StimulationId_TrialStart']):                       
                            print('[SSVEP trial start]', stim.date)
                            if(len(self.ssvep_stims_time) == 0):                                
                                self.ssvep_begin = int(np.floor(stim.date * self.fs))

                        if (stim.identifier == OpenViBE_stimulation['OVTK_StimulationId_VisualSteadyStateStimulationStart']):
                                print('[SSVEP Visual_stim_start]', stim.date)

                        if (stim.identifier >= OVTK_StimulationLabel_Base) and (stim.identifier <= OVTK_StimulationLabel_Base+len(self.frequencies)):
                                self.ssvep_y.append(stim.identifier - OVTK_StimulationLabel_Base)
                                print('[SSVEP stim]', stim.date, self.ssvep_y[-1])
                                self.ssvep_stims_time.append(np.floor(stim.date*self.fs))                                  

                        if(stim.identifier == OpenViBE_stimulation['OVTK_StimulationId_TrialStop']):                            
                            print('[SSVEP trial stop]', stim.date)  

                            self.filter_and_epoch(stim)
                            self.predict()

                            print('[SSVEP] Command to send is: ', self.command)
                            self.feedback_socket.sendto(self.command.encode(), (self.hostname, self.feedback_port))                                                           
                            self.ssvep_pred.append(self.command)
                            
                            self.print_if_target()  
                            self.init_data()
                            self.print_results()                           

                        # Ending Experiment 
                        if stim.identifier == OpenViBE_stimulation['OVTK_StimulationId_ExperimentStop']:
                            self.experiment_end()

            del chunk
        return        

    def unintialize(self):
        pass


box = SSVEPpredictor()

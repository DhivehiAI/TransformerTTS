import subprocess
import shutil
from pathlib import Path

import numpy as np
import tensorflow as tf
import ruamel.yaml

from model.models import Aligner, ForwardTransformer
from utils.scheduling import reduction_schedule


class Config:
    def __init__(self, config_path: str, aligner=False):
        if aligner:
            model_kind = 'aligner'
        else:
            model_kind = 'tts'
        self.config_path = Path(config_path)
        self.model_kind = model_kind
        self.yaml = ruamel.yaml.YAML()
        self.config = self._load_config()
        self.git_hash = self._get_git_hash()
        self.data_name = self.config['data_name']  # raw data
        aligner_config_name = Path(self.config['aligner_config']).stem
        tts_config_name = Path(self.config['tts_config']).stem
        # make session names
        self.session_names = {'data': f"{self.config['text_settings_name']}.{self.config['audio_settings_name']}"}
        self.session_names['aligner'] = f"{aligner_config_name}.{self.session_names['data']}"
        self.session_names['tts'] = f"{tts_config_name}.{aligner_config_name}"
        # create paths
        self.wav_directory = Path(self.config['wav_directory'])
        self.data_dir = Path(f"{self.config['train_data_directory']}.{self.data_name}")
        self.metadata_path = Path(self.config['metadata_path'])
        self.base_dir = Path(self.config['log_directory']) / self.data_name / self.session_names[model_kind]
        self.log_dir = self.base_dir / 'logs'
        self.weights_dir = self.base_dir / 'weights'
        self.train_metadata_path = self.data_dir / f"train_metadata.{self.config['text_settings_name']}.txt"
        self.valid_metadata_path = self.data_dir / f"valid_metadata.{self.config['text_settings_name']}.txt"
        self.phonemized_metadata_path = self.data_dir / f"phonemized_metadata.{self.config['text_settings_name']}.txt"
        self.mel_dir = self.data_dir / f"mels.{self.config['audio_settings_name']}"
        self.pitch_dir = self.data_dir / f"pitch.{self.config['audio_settings_name']}"
        self.duration_dir = self.data_dir / f"durations.{self.session_names['aligner']}"
        self.pitch_per_char = self.data_dir / f"char_pitch.{self.session_names['aligner']}"
        # training parameters
        self.learning_rate = np.array(self.config['learning_rate_schedule'])[0, 1].astype(np.float32)
        if model_kind == 'aligner':
            self.max_r = np.array(self.config['reduction_factor_schedule'])[0, 1].astype(np.int32)
            self.stop_scaling = self.config.get('stop_loss_scaling', 1.)
    
    def _load_config(self):
        all_config = {}
        with open(str(self.config_path), 'rb') as session_yaml:
            session_config = self.yaml.load(session_yaml)
        all_config.update(session_config)
        if 'automatic' in session_config.keys():  # check if it was automatically generated
            return session_config
        else:
            for k in ['data_config', f'{self.model_kind}_config']:
                config_path = session_config[k]
                with open(config_path, 'rb') as config_yaml:
                    config = self.yaml.load(config_yaml)
                    all_config.update(config)
        
        return all_config
    
    @staticmethod
    def _get_git_hash():
        try:
            return subprocess.check_output(['git', 'describe', '--always']).strip().decode()
        except Exception as e:
            print(f'WARNING: could not retrieve git hash. {e}')
    
    def _check_hash(self):
        try:
            git_hash = subprocess.check_output(['git', 'describe', '--always']).strip().decode()
            if self.config['git_hash'] != git_hash:
                print(f"WARNING: git hash mismatch. Current: {git_hash}. Config hash: {self.config['git_hash']}")
        except Exception as e:
            print(f'WARNING: could not check git hash. {e}')
    
    @staticmethod
    def _print_dict_values(values, key_name, level=0, tab_size=2):
        tab = level * tab_size * ' '
        print(tab + '-', key_name, ':', values)
    
    def _print_dictionary(self, dictionary, recursion_level=0):
        for key in dictionary.keys():
            if isinstance(key, dict):
                recursion_level += 1
                self._print_dictionary(dictionary[key], recursion_level)
            else:
                self._print_dict_values(dictionary[key], key_name=key, level=recursion_level)
    
    def print_config(self):
        print('\nCONFIGURATION', self.session_names[self.model_kind])
        self._print_dictionary(self.config)
    
    def update_config(self):
        self.config['git_hash'] = self.git_hash
        self.config['automatic'] = True
    
    def get_model(self, ignore_hash=False):
        if not ignore_hash:
            self._check_hash()
        if self.model_kind == 'aligner':
            return Aligner(mel_channels=self.config['mel_channels'],
                           encoder_model_dimension=self.config['encoder_model_dimension'],
                           decoder_model_dimension=self.config['decoder_model_dimension'],
                           encoder_num_heads=self.config['encoder_num_heads'],
                           decoder_num_heads=self.config['decoder_num_heads'],
                           encoder_feed_forward_dimension=self.config['encoder_feed_forward_dimension'],
                           decoder_feed_forward_dimension=self.config['decoder_feed_forward_dimension'],
                           encoder_maximum_position_encoding=self.config['encoder_max_position_encoding'],
                           decoder_maximum_position_encoding=self.config['decoder_max_position_encoding'],
                           decoder_prenet_dimension=self.config['decoder_prenet_dimension'],
                           encoder_prenet_dimension=self.config['encoder_prenet_dimension'],
                           dropout_rate=self.config['dropout_rate'],
                           decoder_prenet_dropout=self.config['decoder_prenet_dropout'],
                           max_r=self.max_r,
                           mel_start_value=self.config['mel_start_value'],
                           mel_end_value=self.config['mel_end_value'],
                           phoneme_language=self.config['phoneme_language'],
                           with_stress=self.config['with_stress'],
                           debug=self.config['debug'],
                           model_breathing=self.config['model_breathing'])
        
        else:
            return ForwardTransformer(encoder_model_dimension=self.config['encoder_model_dimension'],
                                      decoder_model_dimension=self.config['decoder_model_dimension'],
                                      dropout_rate=self.config['dropout_rate'],
                                      decoder_num_heads=self.config['decoder_num_heads'],
                                      encoder_num_heads=self.config['encoder_num_heads'],
                                      encoder_maximum_position_encoding=self.config['encoder_max_position_encoding'],
                                      decoder_maximum_position_encoding=self.config['decoder_max_position_encoding'],
                                      encoder_feed_forward_dimension=self.config['encoder_feed_forward_dimension'],
                                      decoder_feed_forward_dimension=self.config['decoder_feed_forward_dimension'],
                                      encoder_attention_conv_filters=self.config['encoder_attention_conv_filters'],
                                      decoder_attention_conv_filters=self.config['decoder_attention_conv_filters'],
                                      encoder_attention_conv_kernel=self.config['encoder_attention_conv_kernel'],
                                      decoder_attention_conv_kernel=self.config['decoder_attention_conv_kernel'],
                                      duration_conv_filters=self.config['duration_conv_filters'],
                                      pitch_conv_filters=self.config['pitch_conv_filters'],
                                      duration_kernel_size=self.config['duration_kernel_size'],
                                      pitch_kernel_size=self.config['pitch_kernel_size'],
                                      predictors_dropout=self.config['predictors_dropout'],
                                      mel_channels=self.config['mel_channels'],
                                      encoder_dense_blocks=self.config['encoder_dense_blocks'],
                                      decoder_dense_blocks=self.config['decoder_dense_blocks'],
                                      phoneme_language=self.config['phoneme_language'],
                                      with_stress=self.config['with_stress'],
                                      debug=self.config['debug'],
                                      model_breathing=self.config['model_breathing'])
    
    def compile_model(self, model):
        if self.model_kind == 'aligner':
            model._compile(stop_scaling=self.stop_scaling, optimizer=self.new_adam(self.learning_rate))
        else:
            model._compile(optimizer=self.new_adam(self.learning_rate))
    
    # TODO: move to model
    @staticmethod
    def new_adam(learning_rate, beta_1=0.9, beta_2=0.98, ):
        return tf.keras.optimizers.Adam(learning_rate,
                                        beta_1=beta_1,
                                        beta_2=beta_2,
                                        epsilon=1e-9)
    
    def dump_config(self):
        self.update_config()
        with open(self.base_dir / f"config.yaml", 'w') as model_yaml:
            self.yaml.dump(self.config, model_yaml)
    
    def create_remove_dirs(self, clear_dir=False, clear_logs=False, clear_weights=False):
        self.base_dir.mkdir(exist_ok=True, parents=True)
        self.data_dir.mkdir(exist_ok=True)
        self.pitch_dir.mkdir(exist_ok=True)
        self.pitch_per_char.mkdir(exist_ok=True)
        self.mel_dir.mkdir(exist_ok=True)
        self.duration_dir.mkdir(exist_ok=True)
        if clear_dir:
            delete = input(f'Delete {self.log_dir} AND {self.weights_dir}? (y/[n])')
            if delete == 'y':
                shutil.rmtree(self.log_dir, ignore_errors=True)
                shutil.rmtree(self.weights_dir, ignore_errors=True)
        if clear_logs:
            delete = input(f'Delete {self.log_dir}? (y/[n])')
            if delete == 'y':
                shutil.rmtree(self.log_dir, ignore_errors=True)
        if clear_weights:
            delete = input(f'Delete {self.weights_dir}? (y/[n])')
            if delete == 'y':
                shutil.rmtree(self.weights_dir, ignore_errors=True)
        self.log_dir.mkdir(exist_ok=True)
        self.weights_dir.mkdir(exist_ok=True)
    
    def load_model(self, checkpoint_path: str = None, verbose=True):
        model = self.get_model()
        self.compile_model(model)
        ckpt = tf.train.Checkpoint(net=model)
        manager = tf.train.CheckpointManager(ckpt, self.weights_dir,
                                             max_to_keep=None)
        if checkpoint_path:
            ckpt.restore(checkpoint_path)
            if verbose:
                print(f'restored weights from {checkpoint_path} at step {model.step}')
        else:
            if manager.latest_checkpoint is None:
                print(f'WARNING: could not find weights file. Trying to load from \n {self.weights_dir}.')
                print('Edit config to point at the right log directory.')
            ckpt.restore(manager.latest_checkpoint)
            if verbose:
                print(f'restored weights from {manager.latest_checkpoint} at step {model.step}')
        if self.model_kind == 'aligner':
            reduction_factor = reduction_schedule(model.step, self.config['reduction_factor_schedule'])
            model.set_constants(reduction_factor=reduction_factor)
        return model

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Feb 17 09:57:33 2026

@author: and
"""
import os
import shutil
import pytest
import datetime
from utils import File_Logger
import config_default as config
import pytz

_mock_data = list()
_mock_data.append( dict(current= 1.0,
                   voltage = 1.5))
_mock_data.append( dict(current= 2.0,
                   voltage = 3))
_mock_data.append( dict(current= 3.0,
                   voltage = 10))
_tmp_test_path = '/tmp/pytesting'

@pytest.fixture
def init_and_cleanup(request):
    print("Cleaning up test data path")
    shutil.rmtree(_tmp_test_path,ignore_errors=True)
    os.makedirs(_tmp_test_path)
    yield
    print("Cleaning up test data path")
    shutil.rmtree(_tmp_test_path)
   

def mock_retrieve_data(sequence = "010", start_time = None):
    
    if start_time is None:
        start_time= datetime.datetime(2026,1,1,1,30, tzinfo=pytz.timezone(config.tz))
    
    
    for i, idx in enumerate(sequence):
        t_now = start_time + datetime.timedelta(minutes=i)
        # date_str = (start_time + datetime.timedelta(minutes=i)).strftime(config.time_format)
        # data =  _mock_data[int(idx)]
        # data.update(dict(time = date_str))
        yield  t_now, _mock_data[int(idx)]



def test_write_header_non_existing_file(init_and_cleanup):
    filename = os.path.join(_tmp_test_path, "test_log.txt")

    
    logger = File_Logger(filename, config)
    for t_now, data in mock_retrieve_data('1'):
        logger.log_step(t_now, data)
    
    with open(filename, 'r') as fid:
        header =  fid.readline()
        assert header == 'time,current,voltage\n'
        
def test_skip_duplicated_data_rows(init_and_cleanup):
    
    filename = os.path.join(_tmp_test_path, "log_{date_str}.txt")
   
    n_double = 10
    sequ = '10' + '1'*n_double + '21'
    logger = File_Logger(filename, config)
    for t_now, data in mock_retrieve_data(sequ):
        logger.log_step(t_now, data)
        
    with open(logger.filepath, 'r') as fid:
        file_content =  fid.readlines()
    assert (len(file_content) -1) == len(sequ) - (n_double-2)

def test_skip_duplicated_data_rows_new_file_header(init_and_cleanup):
    
    filename = os.path.join(_tmp_test_path, "log_{date_str}.txt")
    start_time= datetime.datetime(2026,1,1,23,55, tzinfo=pytz.timezone(config.tz))

    n_double = 10
    sequ = '10' + '1'*n_double + '21'
    logger = File_Logger(filename, config)
    for t_now, data in mock_retrieve_data(sequ, start_time=start_time):
        logger.log_step(t_now, data)
        
    for file in ['log_26-01-01.txt', 'log_26-01-02.txt']:
        filepath = os.path.join(_tmp_test_path, file)
        assert os.path.exists(filepath)
        with open(filepath, 'r') as fid:
            header =  fid.readline()
            assert header == 'time,current,voltage\n'
        
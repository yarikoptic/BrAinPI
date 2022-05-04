# -*- coding: utf-8 -*-
"""
Created on Mon May  2 20:44:43 2022

@author: awatson
"""

'''
Map of the browser dictionary/JSON

current_path:
    ['is_file']: bool
    ['root']: str, path to root of directory
    ['dirs']: list, all directories in the current_path, [] = no dirs
    ['files']: list, all files in the currect_path, [] = no files
    
    ['dirs_entries']: list of tuples, 1:1 index list of tuples that maps to ['dirs'] where the tuple is the numer of entries in the directories (num_dirs,num_files)
    
    ['files_stat']: list os.stat objects, 1:1 list that maps os.stat objects with ['files']
    ['files_size']: list of tuples, 1:1 index list of tuples that maps to ['files'] where each tuple is generated by utils.get_file_size
        returning a (size:int, suffix:str, sortindex:int)

'''
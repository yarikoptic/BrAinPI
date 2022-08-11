# -*- coding: utf-8 -*-
"""
Created on Fri Oct 29 09:46:38 2021

@author: alpha
"""

import os, glob, zarr, time, math, sys
import numpy as np
import dask
# from dask.delayed import delayed
import dask.array as da
from skimage import io, img_as_float32, img_as_float64, img_as_uint, img_as_ubyte
# from skimage.transform import rescale, downscale_local_mean
from skimage.filters import gaussian
from numcodecs import Blosc
from distributed import Client
from contextlib import contextmanager

# import h5py
# import hdf5plugin


'''
WORKING FOR ALL RESOLUTION LEVELS 
Fails on big datasets due to dask getting bogged down
Working with sef-contained delayed frunction, but small number of threads makes it slow
2x downsamples only
'''

if os.name == 'nt':
    path = r'Z:\cbiPythonTools\bil_api\converters\H5_zarr_store3'
else:
    path = r'/CBI_FastStore/cbiPythonTools/bil_api/converters/H5_zarr_store3'
    
if path not in sys.path:
    sys.path.append(path)

from H5_zarr_store6 import H5Store
from tiff_manager import tiff_manager, tiff_manager_3d
# from Z:\cbiPythonTools\bil_api\converters\H5_zarr_store3 import H5Store

if os.name == 'nt':
    in_location = r'H:\globus\pitt\bil\fMOST RAW'
else:
    in_location = r'/CBI_Hive/globus/pitt/bil/fMOST RAW'

if os.name == 'nt':
    out_location = r'Z:\testData\h5_zarr_test4'
    # out_location = r'Z:\testData\h5_zarr_test4/scale0'
else:
    out_location = r'/CBI_FastStore/testData/h5_zarr_test4'
    # out_location = r'/CBI_Hive/globus/pitt/bil/h5_zarr_test4/scale0'


class builder:
    
    def __init__(
            self,location,out_location,fileType='tif',
            geometry=(0.35,0.35,1),origionalChunkSize=(1,1,4,1024,1024),finalChunkSize=(1,1,128,128,128),
            sim_jobs=16, compressor=Blosc(cname='zstd', clevel=9, shuffle=Blosc.BITSHUFFLE),
            zarr_store_type='H5', chunk_limit_MB=2048, tmp_dir='/CBI_FastStore/tmp_dask', build_imediately = False
            ):
                
        self.location = location
        self.out_location = out_location
        self.fileType = fileType
        self.geometry = geometry
        self.origionalChunkSize = origionalChunkSize
        self.finalChunkSize = finalChunkSize
        self.sim_jobs = sim_jobs
        self.compressor = compressor
        self.zarr_store_type = zarr_store_type
        self.chunk_limit_MB = chunk_limit_MB
        self.tmp_dir = tmp_dir
        self.store_ext = 'h5'
        
        os.makedirs(self.out_location,exist_ok=True)
        
        ##  LIST ALL FILES TO BE CONVERTED  ##
        ## Assume files are laid out as "color_dir/images"
        filesList = []
        for ii in sorted(glob.glob(os.path.join(self.location,'*'))):
            filesList.append(sorted(glob.glob(os.path.join(ii,'*.{}'.format(self.fileType)))))
        
        # print(filesList)
        
        self.filesList = filesList
        self.Channels = len(self.filesList)
        self.TimePoints = 1
        # print(self.Channels)
        # print(self.filesList)
        
        
        if self.fileType == '.tif' or self.fileType == '.tiff':
            testImage = tiff_manager(self.filesList[0][0])
        else:
            testImage = self.read_file(self.filesList[0][0])
        self.dtype = testImage.dtype
        self.ndim = testImage.ndim
        self.shape_3d = (len(self.filesList[0]),*testImage.shape)
        
        self.shape = (self.TimePoints, self.Channels, *self.shape_3d)
        
        self.pyramidMap = self.imagePyramidNum()
        
        # if build_imediately:
        #     with dask.config.set({'temporary_directory': self.tmp_dir}):
                
        #         # with Client(n_workers=sim_jobs,threads_per_worker=os.cpu_count()//sim_jobs) as client:
        #         # with Client(n_workers=8,threads_per_worker=2) as client:
        #         with Client(n_workers=self.sim_jobs,threads_per_worker=1) as client:
        #             self.write_resolution_series(client)
        
        # if build_imediately:
        #     with dask.config.set({'temporary_directory': self.tmp_dir}):
                
        #         # with Client(n_workers=sim_jobs,threads_per_worker=os.cpu_count()//sim_jobs) as client:
        #         # with Client(n_workers=8,threads_per_worker=2) as client:
        #         with Client(n_workers=self.sim_jobs,threads_per_worker=1) as client:
        #                 self.write_resolution(1,client)
        
    @staticmethod
    def organize_by_groups(a_list,group_len):

        new = []
        working = []
        idx = 0
        for aa in a_list:
            working.append(aa)
            idx += 1
            
            if idx == group_len:
                new.append(working)
                idx = 0
                working = []
        
        if working != []:
            new.append(working)
        return new

    @staticmethod
    def determine_read_depth(storage_chunks,num_workers,z_plane_shape,chunk_limit_MB=1024,cpu_number=os.cpu_count()):
        chunk_depth = storage_chunks[3]
        current_chunks = (storage_chunks[0],storage_chunks[1],storage_chunks[2],chunk_depth,z_plane_shape[1])
        current_size = math.prod(current_chunks)*2/1024/1024
        
        if current_size >= chunk_limit_MB:
            return chunk_depth
        
        while current_size <= chunk_limit_MB:
            chunk_depth += storage_chunks[3]
            current_chunks = (storage_chunks[0],storage_chunks[1],storage_chunks[2],chunk_depth,z_plane_shape[1])
            current_size = math.prod(current_chunks)*2/1024/1024
            
            if chunk_depth >= z_plane_shape[0]:
                chunk_depth = z_plane_shape[0]
                break
        return chunk_depth
            
    
    @contextmanager
    def dist_client(self):
        # Code to acquire resource, e.g.:
        self.client = Client()
        try:
            yield
        finally:
            # Code to release resource, e.g.:
            self.client.close()
            self.client = None

    
    @staticmethod
    def read_file(fileName):
        return io.imread(fileName)
    
    def write_local_res(self,res):
        with Client(n_workers=self.sim_jobs,threads_per_worker=os.cpu_count()//self.sim_jobs) as client:
            self.write_resolution(res,client)
        
        
    
    def imagePyramidNum(self):
        '''
        Map of pyramids accross a single 3D color
        '''
        out_shape = self.shape_3d
        chunk = self.origionalChunkSize[2:]
        pyramidMap = {0:[out_shape,chunk]}
        
        chunk_change = (4,0.5,0.5)
        final_chunk_size = (128,128,128)
        
        current_pyramid_level = 0
        print((out_shape,chunk))
        
        
        while True:
            current_pyramid_level += 1
            out_shape = tuple([x//2 for x in out_shape])
            chunk = (
                chunk_change[0]*pyramidMap[current_pyramid_level-1][1][0],
                chunk_change[1]*pyramidMap[current_pyramid_level-1][1][1],
                chunk_change[2]*pyramidMap[current_pyramid_level-1][1][2]
                )
            chunk = [int(x) for x in chunk]
            chunk = (
                chunk[0] if chunk[0] <= final_chunk_size[0] else final_chunk_size[0],
                chunk[1] if chunk[1] >= final_chunk_size[1] else final_chunk_size[1],
                chunk[2] if chunk[2] >= final_chunk_size[2] else final_chunk_size[0]
                )
            pyramidMap[current_pyramid_level] = [out_shape,chunk]
                
            print((out_shape,chunk))
            
            # if all([x<y for x,y in zip(out_shape,chunk)]):
            #     del pyramidMap[current_pyramid_level]
            #     break
            if any([x<y for x,y in zip(out_shape,chunk)]):
                del pyramidMap[current_pyramid_level]
                break
        
            
        # for key in pyramidMap:
        #     new_chunk = [chunk if chunk <= shape else shape for shape,chunk in zip(pyramidMap[key][0],pyramidMap[key][1])]
        #     pyramidMap[key][1] = new_chunk
        
        print(pyramidMap)
        return pyramidMap
    
    
    @staticmethod
    def regular_path(path):
        return path.replace('\\','/')
    
    def dtype_convert(self,data):
        
        if self.dtype == data.dtype:
            return data
        
        if self.dtype == np.dtype('uint16'):
            return img_as_uint(data)
        
        if self.dtype == np.dtype('ubyte'):
            return img_as_ubyte(data)
        
        if self.dtype == np.dtype('float32'):
            return img_as_float32(data)
        
        if self.dtype == np.dtype(float):
            return img_as_float64(data)
        
        raise TypeError("No Matching dtype : Conversion not possible")
        
    
    def write_resolution_series(self,client):
        '''
        Make downsampled versions of dataset based on pyramidMap
        Requies that a dask.distribuited client be passed for parallel processing
        '''
        for res in range(len(self.pyramidMap)):
            self.write_resolution(res,client)
            
    
    def open_store(self,res):
        return zarr.open(self.get_store(res))
    
    def get_store(self,res):
        if self.zarr_store_type == 'H5':
            print('Getting H5Store')
            # store = self.zarr_store_type(self.scale_name(0),verbose=2)
            store = H5Store(self.scale_name(res),verbose=2)
        else:
            print('Getting Other Store')
            store = self.zarr_store_type(self.scale_name(res))
        return store
    
    def scale_name(self,res):
        name = os.path.join(self.out_location,'scale{}'.format(res))
        print(name)
        return name
        
    
    @staticmethod
    def smooth(image):
        working = img_as_float32(image)
        working = gaussian(working,0.5)
        working = img_as_uint(working)
        return working
        
    
    def write_resolution(self,res,client):
        if res == 0:
            self.write_resolution_0(client)
            return
        
        parent_shape = self.pyramidMap[res-1][0] # Will always be 5-dim (t,c,z,y,x)
        new_shape = self.pyramidMap[res][0]
        
        parent_chunks = self.pyramidMap[res-1][1]
        new_chunks = self.pyramidMap[res][1]
        
        # Assume that each resolution is a 2x downsample May be changed in the future
        downsample_factor = [2]*len(self.pyramidMap)
        
        # parent_array = self.open_store(res-1)
        print('Getting Parent Zarr as Dask Array')
        # parent_array = da.from_zarr(self.get_store(res-1))
        parent_array = zarr.open(self.get_store(res-1))
        parent_array = da.from_array(
            parent_array,
            chunks=(1,1,parent_array.chunks[-3]*8,parent_array.chunks[-2],parent_array.chunks[-1]*8)
            )
        print('parent_array')
        print(parent_array)
        new_array_store = self.get_store(res)
        
        new_shape = (self.TimePoints,self.Channels,*self.pyramidMap[res][0])
        print(new_shape)
        new_chunks = (1,1,*self.pyramidMap[res][1])
        print(new_chunks)
        new_array = zarr.zeros(new_shape, chunks=new_chunks, store=new_array_store, overwrite=True, compressor=self.compressor,dtype=self.dtype)
        print('new_array, {}, {}'.format(new_array.shape,new_array.chunks))
        # z = zarr.zeros(stack.shape, chunks=self.origionalChunkSize, store=store, overwrite=True, compressor=self.compressor,dtype=stack.dtype)

        to_run = []
        for t in range(self.TimePoints):
            for c in range(self.Channels):
                print('Before Subset Parent')
                print(parent_array)
                working_array = parent_array[t,c]
                print('Before Subset working')
                print(working_array)
                working_array = working_array.map_overlap(self.smooth,(1,1,1))
                print('After Smooth working')
                print(working_array)
                working_array = working_array[
                    1::2,
                    1::2,
                    1::2
                    ]
                print('After Subset')
                print(working_array)
                working_array = working_array[None, None, ...]
                
                print('working_array - AFTER subsampling')
                print(working_array)
                print('Storing t-{}, c-{}'.format(t,c))
                da.store(working_array,new_array)
    
    
    def write_resolution_0(self,client):
        
        print('Building Virtual Stack')
        stack = []
        for color in self.filesList:
            
            s = self.organize_by_groups(color,self.origionalChunkSize[2])
            test_image = tiff_manager(s[0][0]) #2D manager
            # chunk_depth = (test_image.shape[1]//4) - (test_image.shape[1]//4)%storage_chunks[3]
            chunk_depth = self.determine_read_depth(self.origionalChunkSize,
                                                    num_workers=self.sim_jobs,
                                                    z_plane_shape=test_image.shape,
                                                    chunk_limit_MB=self.chunk_limit_MB)
            test_image = tiff_manager_3d(s[0],desired_chunk_depth_y=chunk_depth)
            print(test_image.shape)
            print(test_image.chunks)
            
            s = [test_image.clone_manager_new_file_list(x) for x in s]
            print(len(s))
            for ii in s:
                print(ii.chunks)
                print(len(ii.fileList))
            # print(s[-3].chunks)
            print('From_array')
            print(s[0].dtype)
            s = [da.from_array(x,chunks=x.chunks,name=False,asarray=False) for x in s]
            # print(s)
            print(len(s))
            s = da.concatenate(s)
            # s = da.stack(s)
            print(s)
            stack.append(s)
        stack = da.stack(stack)
        stack = stack[None,...]
    
    
        print(stack)
        
        store = self.get_store(0)
        
        z = zarr.zeros(stack.shape, chunks=self.origionalChunkSize, store=store, overwrite=True, compressor=self.compressor,dtype=stack.dtype)
        
        # print(client.run(lambda: os.environ["HDF5_USE_FILE_LOCKING"]))
        da.store(stack,z,lock=False)
    
    
    
    

    
def write_resolution(res):
    if res == 0:
        mr.write_resolution_0()
        return
    
    parent_shape = mr.pyramidMap[res-1][0] # Will always be 5-dim (t,c,z,y,x)
    new_shape = mr.pyramidMap[res][0]
    
    parent_chunks = mr.pyramidMap[res-1][1]
    new_chunks = mr.pyramidMap[res][1]
    
    # Assume that each resolution is a 2x downsample May be changed in the future
    downsample_factor = [2]*len(mr.pyramidMap)
    
    # parent_array = self.open_store(res-1)
    print('Getting Parent Zarr as Dask Array')
    # parent_array = da.from_zarr(self.get_store(res-1))
    parent_array = zarr.open(mr.get_store(res-1))
    parent_array = da.from_array(
        parent_array,
        chunks=(1,1,parent_array.chunks[-3]*8,parent_array.chunks[-2],parent_array.chunks[-1]*8)
        )
    print('parent_array')
    print(parent_array)
    new_array_store = mr.get_store(res)
    
    new_shape = (mr.TimePoints,mr.Channels,*mr.pyramidMap[res][0])
    print(new_shape)
    new_chunks = (1,1,*mr.pyramidMap[res][1])
    print(new_chunks)
    new_array = zarr.zeros(new_shape, chunks=new_chunks, store=new_array_store, overwrite=True, compressor=mr.compressor,dtype=mr.dtype)
    print('new_array, {}, {}'.format(new_array.shape,new_array.chunks))
    # z = zarr.zeros(stack.shape, chunks=self.origionalChunkSize, store=store, overwrite=True, compressor=self.compressor,dtype=stack.dtype)

    to_run = []
    for t in range(mr.TimePoints):
        for c in range(mr.Channels):
            print('Before Subset Parent')
            print(parent_array)
            working_array = parent_array[t,c]
            print('Before Subset working')
            print(working_array)
            working_array = working_array.map_overlap(mr.smooth,(1,1,1))
            print('After Smooth working')
            print(working_array)
            working_array = working_array[
                1::2,
                1::2,
                1::2
                ]
            print('After Subset')
            print(working_array)
            working_array = working_array[None, None, ...]
            
            print('working_array - AFTER subsampling')
            print(working_array)
            print('Storing t-{}, c-{}'.format(t,c))
            da.store(working_array,new_array)
            

if __name__ == '__main__':
    mr = builder(in_location,out_location)
    with dask.config.set({'temporary_directory': mr.tmp_dir}):
            
        # with Client(n_workers=sim_jobs,threads_per_worker=os.cpu_count()//sim_jobs) as client:
        # with Client(n_workers=8,threads_per_worker=2) as client:
        with Client(n_workers=mr.sim_jobs,threads_per_worker=1) as client:
            write_resolution(1)
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
# ## Need to make this conform to ome-ngff
# # https://ngff.openmicroscopy.org/latest/
# def write_z_sharded_array_meta(location, pyramidMap, imageStack, resolution=(1,1,50,1,1), store='zip',axes='tczyx'):
#     metadata = {}
    
#     metadata['shape'] = imageStack.shape
#     metadata['axes'] = axes
    
#     metadata['resolution'] = {}
#     metadata['resolution']['sampling'] = resolution #(t,c,z,y,x)
#     metadata['resolution']['units'] = ('s','c','um','um','um')
    
#     metadata['series'] = {}
#     for key in pyramidMap:
#         metadata['series'][key] = {}
#         metadata['series'][key]['chunks'] = pyramidMap[key][1]
#         metadata['series'][key]['store'] = store
#         metadata['series'][key]['shape'] = pyramidMap[key][0]
#         metadata['series'][key]['dtype'] = str(imageStack.dtype)
    
#     with open(os.path.join(location,'.z_sharded_array'), 'w') as f:
#         json.dump(metadata, f, indent=1)
    
#     return metadata


# def write_to_zip_store(toWrite,location=None):
#     print('In write')
#     if toWrite.shape==(0,0,0):
#         return True
#     with zarr.ZipStore(location) as store:
#         print('In with')
#         print(toWrite.shape)
#         array = zarr.open(store)
#         print('Reading {}'.format(location))
#         # toWrite = toWrite.compute()
#         print('Writing {}'.format(location))
#         array[0:toWrite.shape[0],0:toWrite.shape[1],0:toWrite.shape[2]] = toWrite
#         print('Completed {}'.format(location))
#         return True


# ## Write first resolution 0 and 1 first
# # zarrObjs = {} # Store all zarrObjects for easy write access
# to_compute = []
# for t in range(imageStack.shape[0]):
#     for c in range(imageStack.shape[1]):
#         current_stack = imageStack[t,c]
#         for key in pyramidMap:
#             if key > 0:
#                 break
#             currentShape = current_stack[::2**key,::2**key,::2**key].shape
            
#             for z_shards in range(0,currentShape[0],pyramidMap[key][1][0]):
#                 print(z_shards)
#                 location = os.path.join(out_location,store_location_formatter(key,t,c,z_shards))
                
#                 toWrite = current_stack[z_shards:z_shards+pyramidMap[key][1][0]]
                
#                 future = delayed(write_to_zip_store)(toWrite,location)
#                 # future = toWrite.map_blocks(write_to_zip_store, location=location, dtype=bool)
#                 to_compute.append(future)


# total_jobs = len(to_compute)
# print('Submitting {} of {}'.format(1,total_jobs))
# submit = client.compute(to_compute[0], priority=1)
# to_compute = to_compute[1:]
# submitted = [submit]
# del submit

# idx = 2
# while True:
#     time.sleep(2)
#     if len(to_compute) == 0:
#         break
    
#     while sum( [x.status == 'pending' for x in submitted] ) >= sim_jobs:
#         time.sleep(2)
        
#     print('Submitting {} of {}'.format(idx,total_jobs))
#     submit = client.compute(to_compute[0], priority=idx)
#     to_compute = to_compute[1:]
#     submitted.append(submit)
#     del submit
#     idx += 1
#     submitted = [x for x in submitted if x.status != 'finished']

# submitted = client.gather(submitted)
# del submitted





# def build_array_res_level(location,res):
#     '''
#     Build a dask array representation of a specific resolution level
#     Always output a 5-dim array (t,c,z,y,x)
#     '''
    
#     # Determine the number of TimePoints (int)
#     TimePoints = len(glob.glob(os.path.join(location,str(res),'[0-9]')))
    
#     # Determine the number of Channels (int)
#     Channels = len(glob.glob(os.path.join(location,str(res),'0','[0-9]')))
    
#     # Build a dask array from underlying zarr ZipStores
#     stack = None
#     single_color_stack = None
#     multi_color_stack = None
#     for t in range(TimePoints):
#         for c in range(Channels):
#             z_shard_list = natsort.natsorted(glob.glob(os.path.join(location,str(res),str(t),str(c),'*.zip')))
            
#             single_color_stack = [da.from_zarr(zarr.ZipStore(file),name=file) for file in z_shard_list]
#             single_color_stack = da.concatenate(single_color_stack,axis=0)
#             if c == 0:
#                 multi_color_stack = single_color_stack[None,None,:]
#             else:
#                 single_color_stack = single_color_stack[None,None,:]
#                 multi_color_stack = da.concatenate([multi_color_stack,single_color_stack], axis=1)
            
#         if t == 0:
#             stack = multi_color_stack
#         else:
#             stack = da.concatenate([stack,multi_color_stack], axis=0)
    
#     return stack

# ## Build z_sharded_zip_store
# to_compute = []
# for key in pyramidMap:
#     if key == 0:
#         continue
#     print('Assembling dask array at resolution level {}'.format(key))
#     imageStack = build_array_res_level(out_location,key-1)
    
#     to_compute = []
#     for t in range(imageStack.shape[0]):
#         for c in range(imageStack.shape[1]):
            
#             current_stack = imageStack[t,c] #Previous stack to be downsampled
            
#             mean_downsampled_stack = []
#             # min_shape = current_stack[1::2,1::2,1::2].shape
#             min_shape = pyramidMap[key][0]
#             for z,y,x in product(range(2),range(2),range(2)):
#                 downsampled = current_stack[z::2,y::2,x::2][:min_shape[0],:min_shape[1],:min_shape[2]]
#                 downsampled = downsampled.rechunk()
#                 mean_downsampled_stack.append(downsampled)
#                 del downsampled
            
#             mean_downsampled_stack = da.stack(mean_downsampled_stack)
#             mean_downsampled_stack = mean_downsampled_stack.map_blocks(img_as_float32, dtype=float)
#             mean_downsampled_stack = mean_downsampled_stack.mean(axis=0)
#             mean_downsampled_stack = mean_downsampled_stack.map_blocks(img_as_uint, dtype=np.uint16)
#             # mean_downsampled_stack = mean_downsampled_stack.rechunk(pyramidMap[key][1])
                
            
#             for z_shards in range(0,pyramidMap[key][0][0],pyramidMap[key][1][0]):
#                 print(z_shards)
#                 location = os.path.join(out_location,store_location_formatter(key,t,c,z_shards))
                
#                 toWrite = mean_downsampled_stack[z_shards:z_shards+pyramidMap[key][1][0]]
                
#                 future = delayed(write_to_zip_store)(toWrite,location)
#                 # future = toWrite.map_blocks(write_to_zip_store, location=location, dtype=bool)
#                 # print('Computing Res {}, time {}, channel {}, shard {}'.format(key,t,c,z_shards))
#                 # future = client.compute(future)
#                 # future = client.gather(future)
                
#                 to_compute.append(future)
            
            
#     total_jobs = len(to_compute)
#     print('Submitting {} of {}'.format(1,total_jobs))
#     submit = client.compute(to_compute[0], priority=1)
#     to_compute = to_compute[1:]
#     submitted = [submit]
#     del submit

#     idx = 2
#     while True:
#         time.sleep(2)
#         if len(to_compute) == 0:
#             break
        
#         while sum( [x.status == 'pending' for x in submitted] ) >= sim_jobs:
#             time.sleep(2)
        
#         print('Submitting {} of {}'.format(idx,total_jobs))
#         submit = client.compute(to_compute[0], priority=idx)
#         to_compute = to_compute[1:]
#         submitted.append(submit)
#         del submit
#         idx += 1
#         submitted = [x for x in submitted if x.status != 'finished']

#     submitted = client.gather(submitted)
#     del submitted


# client.close()


# # if __name__ == "__main__":
# #     client = Client()
# #     build()
# #     client.close()
# # else:
# #     print('NOPE')
# #     exit()




# -*- coding: utf-8 -*-
#
# Copyright (c) 2016-2021 B-Open Solutions srl - http://bopen.eu
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections
import os
import sys
import requests
import subprocess
from contextlib import contextmanager
import wslPath
import zipfile
import glob

import fasteners

FOLDER_LOCKFILE_NAME = '.folder_lock'


def selfcheck(tools):
    """Audit the system for issues.

    :param tools: Tools description. Use elevation.TOOLS to test elevation.
    """
    msg = []
    for tool_name, check_cli in collections.OrderedDict(tools).items():
        try:
            subprocess.check_output(check_cli, shell=True, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError:
            msg.append('%r not found or not usable.' % tool_name)
    return '\n'.join(msg) if msg else 'Your system is ready.'


@contextmanager
def lock_tiles(datasource_root, tile_names):
    locks = []
    for tile_name in tile_names:
        lockfile_name = os.path.join(datasource_root, 'cache', tile_name + '.lock')
        locks.append(fasteners.InterProcessLock(lockfile_name))

    for lock in locks:
        lock.acquire(blocking=True)

    yield

    for lock in locks:
        lock.release()


@contextmanager
def lock_vrt(datasource_root, product):
    with fasteners.InterProcessLock(os.path.join(datasource_root, product + '.vrt.lock')):
        yield


def ensure_setup(root, folders=(), file_templates=(), force=False, **kwargs):
    with fasteners.InterProcessLock(os.path.join(root, FOLDER_LOCKFILE_NAME)):
        created_folders = []
        for path in [root] + [os.path.join(root, p) for p in folders]:
            if not os.path.exists(path):
                os.makedirs(path)
                created_folders.append(path)

        created_files = collections.OrderedDict()
        for relpath, template in collections.OrderedDict(file_templates).items():
            path = os.path.join(root, relpath)
            if force or not os.path.exists(path):
                body = template.format(**kwargs)
                with open(path, 'w') as file:
                    file.write(body)
                created_files[path] = body

    return created_folders, created_files


def check_call_make(path, targets=(), variables=()):
    make_targets = ' '.join(targets)
    variables_items = collections.OrderedDict(variables).items()
    make_variables = ' '.join('%s="%s"' % (k.upper(), v) for k, v in variables_items)
    if sys.platform != 'win32':
        cmd = 'make -C {path} {make_targets} {make_variables}'.format(**locals())
        subprocess.check_call(cmd, shell=True)
    else:
        if 'download' in make_targets:
            cmd = []
            for k, files in variables_items:
                for v in files.split(" "):
                    out_file = os.path.join(path,v)
                    tfile = v.replace(".tif",".zip")
                    out_zip = os.path.join(path,tfile)
                    exists = True
                    if not os.path.exists(out_file):
                        url = r'https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF/{}'.format(tfile)
                        myfile = requests.get(url)
                        open(out_zip, 'wb').write(myfile.content)
                        # SAM added exception trap
                        try:
                            with zipfile.ZipFile(out_zip, 'r') as zip_ref:
                                zip_ref.extractall(path)
                        except:
                            print("Failed to extract {}".format(out_zip))
                            exists = False
                    #print("Saved: {}".format(v))
                    if exists:
                        cmd.append(out_file)

        elif 'all' in make_targets:
            cmd = "wsl.exe gdalbuildvrt -q -overwrite {}/{}.vrt {}/*.tif".format(wslPath.to_posix(path),os.path.split(path)[1],wslPath.to_posix(path))
            #print("CMD: ",cmd)
            subprocess.check_call(cmd, shell=True)

        elif 'copy_vrt' in make_targets:
            for k, id in variables_items:
                cmd = "wsl.exe cp {}/{}.vrt {}/{}.{}.vrt".format(wslPath.to_posix(path),os.path.split(path)[1],wslPath.to_posix(path),os.path.split(path)[1],id)
                #print("CMD: ",cmd)
                subprocess.check_call(cmd, shell=True)

        elif 'clip' in make_targets:
            for k, v in variables_items:
                if 'run_id' in k:
                    id = v
                elif 'output' in k:
                    output = v
                else:
                    projwin = v

            vrt = "{}/{}.{}.vrt".format(wslPath.to_posix(path),os.path.split(path)[1],id)
            cmd = "wsl.exe gdal_translate -q -co TILED=YES -co COMPRESS=DEFLATE -co ZLEVEL=9 -co PREDICTOR=2 -projwin {} {} {}".format(projwin,vrt,wslPath.to_posix(output))
            #print("CMD: ",cmd)
            subprocess.check_call(cmd, shell=True)

        elif 'clean' in make_targets:
            searchstr = os.path.join(path.replace("M1","M*"),'*.vrt')
            vrts = glob.glob(searchstr)
            #print("Deleting {} files in {}".format(len(vrts),searchstr))
            for vrt in vrts:
                os.remove(vrt)
            cmd = ""
        else:
            wsl_path = wslPath.to_posix(path)
            cmd = 'wsl.exe make -C {} {} {}'.format(wsl_path,make_targets,make_variables)
            #print("CMD: ",cmd)
            subprocess.check_call(cmd, shell=True)
    return cmd

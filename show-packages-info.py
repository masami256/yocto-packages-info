#!/usr/bin/env python3

import subprocess
from optparse import OptionParser
from stat import *
import sys
import os

def run_cmd(cmd):
    lines = []
    
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        proc.wait()
        
        retcode = proc.returncode

        for line in proc.stdout.readlines():
            lines.append(line.decode('utf-8'))

        return {
            "returncode": int(retcode),
            "lines": lines
        }
    return None

def has_bitbake():
    cmd = ["which", "bitbake-layers"]
    result = run_cmd(cmd)
    if not result["returncode"] == 0:
        print("[*] bitbake-layers command isn't in your $PATH")
        exit(-1)

def get_layers():
    cmd = ["bitbake-layers", "show-layers"]

    layers = {}
    
    result = run_cmd(cmd)
    lines = result["lines"]

    # remove header lines
    for i in range(3):
        lines.pop(0)
        
    for line in lines:
        tmp = line.strip().split()
        layer = {
            "name": tmp[0],
            "path": tmp[1],
            "prio": int(tmp[2])
        }

        layers[layer["name"]] = layer

    return layers

def get_recipes():
    cmd = ["bitbake-layers", "show-recipes"]

    recipes = {}

    result = run_cmd(cmd)

    lines = result["lines"]
    length = len(lines)

    # skip headers
    i = 0
    while True:
        if i >= length:
            break
        if lines[i].strip().endswith(':'):
            break
        i += 1
        
    for n in range(i):
        lines.pop(0)

    length = len(lines)        
    i = 0
    while True:
        if i >= length:
            break
        
        recipe = {}
        line = lines[i].strip()
        if line.endswith(':'):
            recipe["name"] =  line[0:len(line) - 1].strip()

            layers = {}
            
            i += 1
            while True:
                if i >= length:
                    break

                line = lines[i].strip()
                if line.endswith(':'):
                    break

                info = line.split(' ')

                layer = info[0]
                version = info[len(info) - 1]
                layer_info = {
                    "layer": layer,
                    "version": version
                }

                layers[layer] = layer_info
                i += 1

            recipe["layers"] = layers
            recipes[recipe["name"]] = recipe
            
    return recipes

def read_license_manifest(license_dir):

    licenses = {}
    path = "%s/license.manifest" % license_dir
    with open(path, "r") as f:
        lines = f.readlines()
        length = len(lines)

        i = 0
        while True:
            if i >= length:
                break
            
            line = lines[i].strip()

            if len(line) > 0:
                pkg_name = lines[i].strip().split(':')
                pkg_version = lines[i + 1].strip().split(':')
                pkg_recipe_name = lines[i + 2].strip().split(':')
                pkg_license = lines[i + 3].strip().split(':')

                lic_info = {
                    "name": pkg_name[1].strip(),
                    "version": pkg_version[1].strip(),
                    "recipe": pkg_recipe_name[1].strip(),
                    "pkg_license": pkg_license[1].strip()
                }

                licenses[lic_info["name"]] = lic_info
                
                i += 4
            else:
                i += 1           

    return licenses

def read_all_package_licenses(license_dir):
    licenses = {}
    
    for root, dirs, files in os.walk(license_dir):
        for dir in dirs:
            recipeinfo = "%s/%s/recipeinfo" % (license_dir, dir)
            if os.path.exists(recipeinfo):
                with open(recipeinfo, "r") as f:
                    lines = f.readlines()

                    lic_info = {
                        "name": dir,
                        "pkg_license": lines[0].split(':')[1].strip(),
                        "version": lines[2].split(':')[1].strip(),
                    }

                    licenses[lic_info["name"]] = lic_info

    return licenses

def set_package_recipe(licenses, recipes):
    for k in licenses.keys():
        name = k

        if not name in recipes:
            # check without -native suffix. e.g. nss-native to nss
            if name.endswith("-native"):
                tmpname = name[0:len(name) - 7]

            if tmpname in recipes:
                name = tmpname
            else:
                print("[*] %s is not in recipe" % name, file=sys.stderr)
                continue
        
        licenses[k]["recipe"] = recipes[name]["name"]
        
def merge_data(layers, recipes, licenses):
    data = {}

    for pkg in licenses.keys():
        lic_info = licenses[pkg]
        pkg_name = lic_info["name"]
        recipe_name = lic_info["recipe"]

        # get recipe for the package
        recipe = recipes[recipe_name]

        prev = None
        layer = None
        # get layer for the package
        for l in recipe["layers"]:
            if prev is None:
                layer = layers[l]
            else:
                tmp = layers[l]

                if tmp["prio"] > prev["prio"]:
                    layer = tmp

            prev = layers[l]

        data[pkg_name] = {
            "pkg_name": pkg_name,
            "recipe_name": recipe_name,
            "layer": layer["name"],
            "version": lic_info["version"],
            "license": lic_info["pkg_license"]
        }

    return data

def is_target_layer(layer, target_layers):
    return layer in target_layers
        
def create_verbose_data(data, target_layers):
    result = {}

    for k in data.keys():
        d = data[k]

        if target_layers is None or is_target_layer(d["layer"], target_layers):
            result[k] = d

    return result

def show_no_data(layers):
    print("Packages not use %s layers" % ",".join(layers))

def show_result(data, show_all, target_layers):
    if len(data) == 0:
        show_no_data(target_layers)
        return
    
    if not show_all and target_layers is not None:
        layers = ",".join(target_layers)    
        print("===== Package in layer %s ====" % layers)
    else:
        print("==== Packages info ====")

    print("%s\t%s\t%s\t%s\t%s" % ("package name".ljust(30), "layer".ljust(20), "recipe name".ljust(30), "version".ljust(10), "license".ljust(20)))
    for k in data.keys():
        d = data[k]
        print("%s\t%s\t%s\t%s\t%s" % (d["pkg_name"].ljust(30), d["layer"].ljust(20), d["recipe_name"].ljust(30), d["version"].ljust(10), d["license"].ljust(20)))

def show_version():
    print("%s version 0.1" % os.path.basename(sys.argv[0]))
    exit(0)

def license_dir_exists(path):
    if path is None:
        return False
    
    return os.path.exists(path)

def show_licence_dir_error(path):
    print("licence directory [%s] is not found" % path, file=sys.stderr)
    exit(1)
    
def parse_arguments():
    usage = "usage: %prog [options] licence_directory"
    
    parser = OptionParser(usage=usage)

    parser.add_option("-l", "--layers", dest="layer_names",
                      help="comma separeted layer names",
                      metavar="layers", default=None)
    
    parser.add_option("-v", "--version", dest="version",
                      help="show program version",
                      action="store_true", default=False)

    parser.add_option("-a", "--all", dest="all_info",
                      help="show all package info",
                      action="store_true", default=False)

    parser.add_option("-r", "--rootfs", dest="rootfs",
                       help="check package in rootfs",
                       action="store_true", default=False)

    (options, args) = parser.parse_args()

    if len(args) == 0:
        print("must specify license directory", file=sys.stderr)
        exit(1)
    
    return {
        "license_directory": args[0],
        "version": options.version,
        "all": options.all_info,
        "layer_names": options.layer_names,
        "rootfs": options.rootfs,
    }

if __name__ == "__main__":
    args = parse_arguments()
    
    if args["version"]:
        show_version()

    if not license_dir_exists(args["license_directory"]):
        show_licence_dir_error(args["license_directory"])
        
    has_bitbake()
    layers = get_layers()
    recipes = get_recipes()

    check_target_layers = None
    if args["layer_names"]:
        check_target_layers = args["layer_names"].split(',')
        
    licenses = None

    if args["rootfs"]:
        licenses = read_license_manifest(args["license_directory"])
    else:
        licenses = read_all_package_licenses(args["license_directory"])
        set_package_recipe(licenses, recipes)

    data = merge_data(layers, recipes, licenses)
    
    if not args["all"]:
        data = create_verbose_data(data, check_target_layers)

    show_result(data, args["all"], check_target_layers)

    exit(0)

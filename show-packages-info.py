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

def find_packages_not_built_from_debian(packages, licenses, base_workdir):
    cmd = ["find", base_workdir, "-maxdepth", "2", "-type", "d"]
    
    result = run_cmd(cmd)

    package_dirs = result["lines"]
    result = {}
    
    for package_dir in package_dirs:
        
        package_dir = package_dir.strip()
        pkgname = os.path.basename(package_dir)
        actual_pkgname = pkgname
        if pkgname.endswith("-native"):
            pkgname = pkgname.strip("-native")

        if actual_pkgname in packages.keys():
            if actual_pkgname in licenses:
                lic = licenses[actual_pkgname]

                cmd = ["find", package_dir, "-maxdepth", "2", "-name", "*.dsc"]
                dsc_result = run_cmd(cmd)

                if len(dsc_result["lines"]) is 0:
                    result[actual_pkgname] = packages[actual_pkgname]
                
    return result
                
def get_bitbake_envs():
    cmd = ["bitbake", "-e"]
    lines = []

    result = {}

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        for line in proc.stdout.readlines():
            l = line.decode('utf-8')
    
            if l.startswith("BASE_WORKDIR=") or \
               l.startswith("TMPDIR="):
                tmp  = l.strip().replace('"', '').split('=')
                result[tmp[0]] = tmp[1]

    if len(result) is 0:
        print("Cannot get BASE_WORKDIR environment", file=sys.stderr)
        exit(1)

    return result

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

def get_packages_in_rootfs(license_dir):
    packages = []
    path = "%s/license.manifest" % license_dir

    with open(path, "r") as f:
        lines = f.readlines()

        for line in lines:
            if line.startswith("PACKAGE NAME:"):
                name = line.strip().split(':')[1].strip()
                packages.append(name)

    return packages

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
                        "pr": lines[1].split(':')[1].strip(),
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

def show_no_data():
    print("All packages are built from debian source!")

def show_result(data):
    if len(data) == 0:
        show_no_data()
        return 0
    
    print("==== Packages not built from debian source ====")

    print("%s\t%s\t%s\t%s\t%s" % ("package name".ljust(30), "layer".ljust(20), "recipe name".ljust(30), "version".ljust(10), "license".ljust(20)))
    for k in data.keys():
        d = data[k]
        print("%s\t%s\t%s\t%s\t%s" % (d["pkg_name"].ljust(30), d["layer"].ljust(20), d["recipe_name"].ljust(30), d["version"].ljust(10), d["license"].ljust(20)))

    return 1

def show_version():
    print("%s version 0.1" % os.path.basename(sys.argv[0]))
    exit(0)

def license_dir_exists(path):
    if path is None:
        return False
    
    return os.path.exists(path)

def parse_arguments():
    parser = OptionParser()

    parser.add_option("-r", "--rootfs", dest="rootfs",
                       help="path to image directory(e.g. $BASE_WORKDIR/tmp/deploy/licenses/core-image-minimal-qemuarm64-20190507062402)",
                       metavar="ROOTFS", default=None)

    (options, args) = parser.parse_args()

    return {
        "rootfs": options.rootfs,
    }

if __name__ == "__main__":
    args = parse_arguments()

    has_bitbake()

    bitbake_envs = get_bitbake_envs()
    
    layers = get_layers()
    recipes = get_recipes()

    license_dir = "%s/deploy/licenses" % bitbake_envs["TMPDIR"]

    licenses = read_all_package_licenses(license_dir)
    set_package_recipe(licenses, recipes)

    all_packages = merge_data(layers, recipes, licenses)
    packages = None

    if not args["rootfs"]:
        packages = all_packages
    else:
        rootfs_packages = get_packages_in_rootfs(args["rootfs"])
        packages = {}
        for k in all_packages:
            pkgname = all_packages[k]["pkg_name"]
            if pkgname in rootfs_packages:
                packages[k] = all_packages[k]


    packages = find_packages_not_built_from_debian(packages, licenses, bitbake_envs["BASE_WORKDIR"])

    r = 0
    sorted_packages = {}
    for k, v in sorted(packages.items(), key=lambda x: x[0]):
        sorted_packages[k] = v
    r = show_result(sorted_packages)

    exit(r)

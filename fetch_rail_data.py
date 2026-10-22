"""Download India's railway lines (OpenStreetMap via HOT's raw-data export) once, into data/india_rail.gpkg.

Sources: https://data.humdata.org/dataset/hotosm_ind_railways  (railway lines; ODbL, (c) OpenStreetMap contributors; 13 MB download, 24 MB on disk)
         https://github.com/datameet/railways  (station codes + coordinates, DataMeet; 2 MB)
Run:  python fetch_rail_data.py
"""
import os, subprocess, sys, urllib.request, zipfile

URL = "https://s3.dualstack.us-east-1.amazonaws.com/production-raw-data-api/ISO3/IND/railways/lines/hotosm_ind_railways_lines_gpkg.zip"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
os.makedirs(OUT, exist_ok=True)
zp = os.path.join(OUT, "india_rail_gpkg.zip")

print("Downloading", URL)
try:
    urllib.request.urlretrieve(URL, zp)
except Exception as e:                      # some Python installs lack the right CA certificates; curl uses the OS store
    print("urllib failed (%s), trying curl" % e)
    subprocess.run(["curl", "-L", "-o", zp, URL], check=True)

with zipfile.ZipFile(zp) as z:
    name = next(n for n in z.namelist() if n.endswith(".gpkg"))
    with z.open(name) as src, open(os.path.join(OUT, "india_rail.gpkg"), "wb") as dst:
        dst.write(src.read())
os.remove(zp)
print("Saved", os.path.join(OUT, "india_rail.gpkg"), "-", os.path.getsize(os.path.join(OUT, "india_rail.gpkg")) // 1000000, "MB")

# station list (code -> coordinates) so routes can be traced without any online lookup
ST_URL = "https://raw.githubusercontent.com/datameet/railways/master/stations.json"
sp = os.path.join(OUT, "stations.json")
try:
    urllib.request.urlretrieve(ST_URL, sp)
except Exception as e:
    print("urllib failed (%s), trying curl" % e)
    subprocess.run(["curl", "-L", "-o", sp, ST_URL], check=True)
print("Saved", sp, "-", os.path.getsize(sp) // 1000, "KB")

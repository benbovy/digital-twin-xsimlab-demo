import requests
from urllib.parse import urljoin

import stackstac
import xarray as xr
from pathlib import Path
from ipyleaflet import Rectangle
from satstac import Collection, Item, ItemCollection


def stac_search(leaflet_map, url, collections, page_limit=100, limit=10000, **kwargs):
    params = {
        'intersects': leaflet_map.draw_features[-1]['geometry'],
        'collections': ["ch.swisstopo.swissalti3d"],
        'limit': limit,
    }
    params.update(kwargs)

    nextlink = {
        'method': 'POST',
        'href': urljoin(url, 'search'),
        'headers': None,
        'body': params,
        'merge': False
    }

    items = []
    while nextlink and len(items) < params["limit"]:
        if nextlink.get('method', 'GET') == 'GET':
            resp = requests.post(url=nextlink['href'], headers=None, **params)
        else:
            _headers = nextlink.get('headers', {})
            _body = nextlink.get('body', {})
            _body.update({'limit': page_limit})

            if nextlink.get('merge', False):
                _headers.update(headers or {})
                _body.update(params)
            resp = requests.post(url=nextlink['href'], headers=_headers, json=_body).json()
        items += [Item(i) for i in resp['features']]
        links = [l for l in resp['links'] if l['rel'] == 'next']
        nextlink = links[0] if len(links) == 1 else None

    # retrieve collections
    collections = []
    try:
        for c in set([item._data['collection'] for item in items if 'collection' in item._data]):
            _url = urljoin(url, 'collections/%s' % c)
            col = Collection(requests.post(url=_url, headers=None))
            collections.append(col)
            #del collections[c]['links']
    except:
        pass

    return ItemCollection(items, collections=collections)


def get_swiss_elevation(leaflet_map, resolution=2):
    items = stac_search(
        leaflet_map,
        "https://data.geo.admin.ch/api/stac/v0.9/",
        ["ch.swisstopo.swissalti3d"],
        datetime="2019-01-01",
        limit=100
    )
    
    # keep only the tif asset at the given resolution
    # rename all asset keys to "elevation" (otherwise every asset is
    # considered as a separate band)
    for i in items._items:
        iid = i._data["id"]
        assets = i._data["assets"]
        for k in list(assets):
            a = assets.pop(k)
            if k.startswith(f"{iid}_{resolution}_") and k.endswith(".tif"):
                assets['elevation'] = a
    
    # hack: sum over time as stackstac returns one time item per asset
    da = stackstac.stack(list(items), resolution=resolution).squeeze().sum('time')
    
    return items, da


def get_srtm_data(leaflet_map):
    lat, lon = list(zip(*leaflet_map.draw_features[-1]['geometry']['coordinates'][0]))
    bbox = [min(lon), max(lon), min(lat), max(lat)]
    
    url = "https://portal.opentopography.org/API/globaldem"
    params = {
        "demtype": "SRTMGL3",
        "south": bbox[0],
        "north": bbox[1],
        "west": bbox[2],
        "east": bbox[3],
        "outputFormat": "GTiff",
    }
    
    fbbox = '-'.join([str(b) for b in bbox])
    fname = Path("data") / f"srtm_{fbbox}.tif"

    if not fname.is_file():
        response = requests.get(url, params=params, stream=True)
        response.raise_for_status()

        with fname.open("wb") as fp:
            for chunk in response.iter_content(chunk_size=None):
                fp.write(chunk)

    dem = xr.open_dataarray(fname)
    dem_bbox = dem.rio.bounds()
    rect = Rectangle(bounds=[(dem_bbox[1], dem_bbox[0]), (dem_bbox[3], dem_bbox[2])])
    
    return dem.rio.reproject(dem.rio.estimate_utm_crs()).squeeze(), rect
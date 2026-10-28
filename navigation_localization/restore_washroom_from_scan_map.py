from project_config import map_path
"""Restore only the washroom from the saved ray-traced projection of the original 3D scans.

The source was reconstructed using leveled/dewarped 3D lidar returns 0.2--1.4 m
above ground and SLAM ray tracing. It includes observed free space, unlike a
point-only occupied projection. No unobserved cells are made free here.
"""
from pathlib import Path
import json
import shutil
import time
import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'offline_2d_20261009'
BOUNDS = {'x': [-20.2, -16.2], 'y': [-4.6, 3.3]}


def prepare():
    config = yaml.safe_load((map_path('map.yaml')).read_text())
    original = yaml.safe_load((SOURCE/'map.yaml').read_text())
    for key in ('resolution', 'origin', 'negate', 'occupied_thresh'):
        assert config[key] == original[key], '原始投影和当前栅格坐标不一致：'+key
    source = np.flipud(np.array(Image.open(SOURCE/original['image'])))
    resolution = config['resolution']; ox, oy, yaw = config['origin']
    assert yaw == 0
    h, w = source.shape
    x = ox+(np.arange(w)+.5)*resolution
    y = oy+(np.arange(h)+.5)*resolution
    mask = ((y[:,None]>=BOUNDS['y'][0]) & (y[:,None]<=BOUNDS['y'][1]) &
            (x[None,:]>=BOUNDS['x'][0]) & (x[None,:]<=BOUNDS['x'][1]))
    outputs = {}
    records = {}
    for name in ('map.pgm', 'map_cleaned.pgm'):
        old = np.flipud(np.array(Image.open(map_path(name))))
        assert old.shape == source.shape
        updated = old.copy(); updated[mask] = source[mask]
        assert np.array_equal(updated[~mask], old[~mask])
        assert np.array_equal(updated[mask], source[mask])
        outputs[name] = updated
        records[name] = {'changed_cells':int(np.count_nonzero(updated!=old)),
            'restored_occupied_cells':int(np.count_nonzero(mask & (updated==0) & (old!=0))),
            'new_observed_free_cells':int(np.count_nonzero(mask & (updated==254) & (old!=254))),
            'hand_filled_free_reverted_to_unknown':int(np.count_nonzero(mask & (old==254) & (updated==205))),
            'outside_changed_cells':int(np.count_nonzero((updated!=old) & ~mask))}
    backup = ROOT/'backups'/('washroom_observed_'+time.strftime('%Y%m%d_%H%M%S'))
    backup.mkdir(parents=True)
    for name in outputs:
        shutil.copy2(map_path(name),backup/name)
        Image.fromarray(np.flipud(outputs[name])).save(backup/(name+'.candidate.pgm'),format='PPM')
    report={'source':str(SOURCE/original['image']), 'source_3d_scan_session':'floor_20261009_100455',
            'source_processing': 'gravity leveling, motion compensation, 0.2–1.4m above ground, SLAM ray tracing',
            'bounds':BOUNDS,'resolution':resolution,'origin':config['origin'],
            'backup':str(backup),'files':records,'applied':False}
    (ROOT/'washroom_restore_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':prepare()

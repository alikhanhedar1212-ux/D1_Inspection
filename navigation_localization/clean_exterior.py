from pathlib import Path
import json,yaml,numpy as np
from PIL import Image
from matplotlib.path import Path as Polygon
from scipy.ndimage import binary_dilation,distance_transform_edt,label
r=Path(__file__).parent
source=r/'map_before_exterior_cleanup.pgm'
if not source.exists():source.write_bytes((r/'map.pgm').read_bytes())
a=np.flipud(np.array(Image.open(source)));h,w=a.shape;x=-31.5+(np.arange(w)+.5)*.05;y=-21.9+(np.arange(h)+.5)*.05;xx,yy=np.meshgrid(x,y)
# Outer wall outline; doors terminate at existing indoor virtual boundaries.
vertices=[[-28.35,3.0],[-22.25,3.0],[-22.25,-3.65],[-19.2,-3.85],[-19.2,-3.55],[-17.2,-3.55],[-17.2,-3.95],[-11.05,-4.15],[-11.05,-3.95],[-8.95,-3.95],[-8.95,-4.25],[-4.75,-4.45],[-4.75,2.0],[1.8,2.0],[2.25,1.55],[2.4,-4.55],[2.05,-5.9],[1.8,-6.9],[2.25,-7.3],[2.25,-11.8],[1.75,-13.8],[.8,-14.15],[-4.2,-14.3],[-5.7,-14.5],[-5.7,-13.85],[-6.8,-13.85],[-6.8,-14.45],[-12.8,-14.05],[-13.,-13.6],[-22.7,-13.45],[-23.9,-13.3],[-23.7,-12.25],[-28.65,-12.15],[-28.65,-6.4],[-28.35,-4.2]]
mask=Polygon(vertices).contains_points(np.column_stack([xx.ravel(),yy.ravel()])).reshape(h,w);mask=distance_transform_edt(~mask)*.05<=.15
out=a.copy();out[~mask]=205
Image.fromarray(np.flipud(out)).save(r/'map_cleaned.pgm')
cfg=yaml.safe_load((r/'map.yaml').read_text());cfg['image']='map_cleaned.pgm';(r/'map_cleaned.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
report={'source':source.name,'output':'map_cleaned.pgm','exterior_polygon_xy':vertices,'wall_margin_m':.15,'occupied_removed':int(np.count_nonzero((a==0)&~mask)),'free_exterior_changed_to_unknown':int(np.count_nonzero((a==254)&~mask)),'inside_changed_cells':int(np.count_nonzero((a!=out)&mask))};(r/'exterior_cleanup.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='exterior_polygon_xy'}))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig,axs=plt.subplots(1,2,figsize=(16,7))
for ax,img,title in zip(axs,[a,out],['Before','After: exterior unknown']):
 ax.imshow(img,origin='lower',cmap='gray',vmin=0,vmax=255,extent=[-31.5,15.9,-21.9,9.5]);ax.set_title(title);ax.set_xlim(-30,5);ax.set_ylim(-18,6)
fig.tight_layout();fig.savefig(r/'cleanup_comparison.png',dpi=110)
for f in ['planner.yaml','motion.yaml']:
 p=yaml.safe_load((r/f).read_text())
 for key in ['global_costmap','local_costmap']:
  if key in p:p[key][key]['ros__parameters']['inflation_layer']['inflation_radius']=.4
 (r/f).write_text(yaml.safe_dump(p,sort_keys=False))

from pathlib import Path
import numpy as np,yaml,json
from scipy import ndimage
from PIL import Image
root=Path(__file__).parent;m=yaml.safe_load((root/'map.yaml').read_text());grid=np.flipud(np.asarray(Image.open(root/'map.pgm')));res=m['resolution'];origin=np.array(m['origin'][:2]);occ=grid<50;free=grid>250;field=ndimage.distance_transform_edt(~occ)*res;scan=np.load(root/'live_scan.npz');ranges=scan['ranges'];angles=float(scan['angle_min'])+np.arange(len(ranges))*float(scan['angle_increment']);mask=np.isfinite(ranges)&(ranges>.6)&(ranges<15);indices=np.where(mask)[0];indices=indices[np.linspace(0,len(indices)-1,min(120,len(indices))).astype(int)];points=np.column_stack((np.cos(angles[indices])*ranges[indices],np.sin(angles[indices])*ranges[indices]));height,width=grid.shape
clear=ndimage.distance_transform_edt(free)*res;ys,xs=np.where((clear>.25)&(np.indices(grid.shape)[0]%10==0)&(np.indices(grid.shape)[1]%10==0));candidates=np.column_stack((origin[0]+(xs+.5)*res,origin[1]+(ys+.5)*res))
def score(positions,yaw):
 rotated=points@np.array([[np.cos(yaw),np.sin(yaw)],[-np.sin(yaw),np.cos(yaw)]])
 endpoint=positions[:,None,:]+rotated;cells=np.floor((endpoint-origin)/res).astype(int);x=cells[:,:,0];y=cells[:,:,1];valid=(x>=0)&(x<width)&(y>=0)&(y<height);x=np.clip(x,0,width-1);y=np.clip(y,0,height-1);dist=field[y,x];hit=np.exp(-.5*(dist/.2)**2)*valid
 return np.mean(hit,axis=1)
coarse=[]
for yaw in np.arange(-np.pi,np.pi,np.pi/36):
 s=score(candidates,yaw);ids=np.argpartition(s,-8)[-8:]
 for i in ids:coarse.append([float(s[i]),float(candidates[i,0]),float(candidates[i,1]),float(yaw)])
coarse.sort(reverse=True);seeds=[]
for p in coarse:
 if all(np.hypot(p[1]-v[1],p[2]-v[2])>.7 or abs(np.arctan2(np.sin(p[3]-v[3]),np.cos(p[3]-v[3])))>.3 for v in seeds):seeds.append(p)
 if len(seeds)==12:break
refined=[]
for old,x,y,yaw in seeds:
 offsets=np.array([(dx,dy) for dx in np.arange(-.4,.401,.05) for dy in np.arange(-.4,.401,.05)]);positions=np.array([x,y])+offsets;cells=np.floor((positions-origin)/res).astype(int);good=free[cells[:,1],cells[:,0]];positions=positions[good]
 best=None
 for angle in np.arange(yaw-.12,yaw+.121,.01):
  s=score(positions,angle);i=int(s.argmax());p=[float(s[i]),float(positions[i,0]),float(positions[i,1]),float(np.arctan2(np.sin(angle),np.cos(angle)))]
  if best is None or p[0]>best[0]:best=p
 refined.append(best)
refined.sort(reverse=True);report={'scan_timestamp':float(scan['stamp']),'observed_sampled_beams':len(points),'hypotheses':[{'score':p[0],'x':p[1],'y':p[2],'yaw':p[3]} for p in refined[:6]],'status':'仅为自动粗定位候选，需要实时扫描叠加与现场位置核对'};(root/'initial_pose_candidates.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False),flush=True)
np.save(root/'matching_points.npy',points)

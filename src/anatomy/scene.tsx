import {useEffect,useRef} from 'react';
import * as T from 'three';
import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/examples/jsm/environments/RoomEnvironment.js';
import {mergeGeometries} from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import {createExplosionLayout} from './explosion-layout';
import {decodeModelResponse} from './model-download';
import {PointerTap} from './pointer-tap';
import {SYSTEMS,type Atlas,type SceneState} from './anatomy';
interface Props {atlas:Atlas;state:SceneState;theme:'light'|'dark';onSelect:(id:string)=>void;onProgress:(n:number)=>void;onError:(s:string)=>void}
export default function AnatomyScene({atlas,state,theme,onSelect,onProgress,onError}:Props){
 const host=useRef<HTMLDivElement>(null),latest=useRef(state),latestTheme=useRef(theme),select=useRef(onSelect);
 latest.current=state;latestTheme.current=theme;select.current=onSelect;
 useEffect(()=>{
  const el=host.current!;let disposed=false,frame=0,dirty=true,ready=false,lastView='',lastReset=-1,lastIsolate='',layoutKey='',amount=0,lastZoom=state.zoom??1,lastOpacity=-1;
  let lastState:SceneState|null=null;
  const abort=new AbortController();
  let renderer:T.WebGLRenderer;
  try{renderer=new T.WebGLRenderer({antialias:true,alpha:true,powerPreference:'high-performance'});}catch{onError('This browser could not start the 3D viewer. Please try a browser with WebGL enabled.');return;}
  renderer.setPixelRatio(Math.min(devicePixelRatio,innerWidth<768?1.5:2));renderer.setClearColor('#15171c',0);renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;el.appendChild(renderer.domElement);
  renderer.domElement.tabIndex=0;
  renderer.domElement.setAttribute('role','application');
  renderer.domElement.setAttribute('aria-label','Interactive human anatomy. Drag to orbit, scroll to zoom, and click to inspect. Keyboard: arrow keys orbit, Shift and arrow keys pan, plus and minus zoom, Home resets the view, and Enter selects the center structure.');
  const scene=new T.Scene(),camera=new T.PerspectiveCamera(34,1,.005,100),controls=new OrbitControls(camera,renderer.domElement);
  camera.position.set(1.4,1.05,3.6);controls.target.set(0,.85,0);controls.enableDamping=true;controls.dampingFactor=.085;controls.minDistance=.07;controls.maxDistance=40;controls.maxPolarAngle=Math.PI*.96;controls.addEventListener('change',()=>{dirty=true;});
  const pmrem=new T.PMREMGenerator(renderer),room=new RoomEnvironment(),env=pmrem.fromScene(room,.04);scene.environment=env.texture;room.dispose();pmrem.dispose();
  scene.add(new T.HemisphereLight(0xffffff,0xa7acb2,1.05));
  const key=new T.DirectionalLight(0xfffaf4,2.3);key.position.set(-2,4,3);scene.add(key);
  const rim=new T.DirectionalLight(0xe9f0ff,1.8);rim.position.set(2,2,-3);scene.add(rim);
  const platform=new T.Mesh(new T.CylinderGeometry(.47,.5,.008,100),new T.MeshStandardMaterial({color:0x242830,metalness:.15,roughness:.82}));platform.position.y=-.011;scene.add(platform);
  const ring=new T.Mesh(new T.RingGeometry(.5,.502,128),new T.MeshBasicMaterial({color:0x7a8796,transparent:true,opacity:.25,side:T.DoubleSide}));ring.rotation.x=-Math.PI/2;ring.position.y=-.005;scene.add(ring);
  const width=T.MathUtils.ceilPowerOfTwo(atlas.parts.length),data=new Float32Array(width*4),partTexture=new T.DataTexture(data,width,1,T.RGBAFormat,T.FloatType);partTexture.needsUpdate=true;
  const selectedData=new Uint8Array(width*4),selectionTexture=new T.DataTexture(selectedData,width,1);selectionTexture.needsUpdate=true;
  const materials:T.Material[]=[],geometries:T.BufferGeometry[]=[],pickers:(T.Mesh|undefined)[]=[],pickingMaterial=new T.MeshBasicMaterial({side:T.DoubleSide}),centers=atlas.parts.map(p=>new T.Vector3().fromArray(p.bounds[0]).add(new T.Vector3().fromArray(p.bounds[1])).multiplyScalar(.5));
  const offsets:T.Vector3[]=[],bounds=atlas.parts.map(p=>new T.Box3(new T.Vector3().fromArray(p.bounds[0]),new T.Vector3().fromArray(p.bounds[1])));
  let packingWidth=1,packingHeight=1;
  const markerPositions=new Float32Array(atlas.parts.length*3),markerGeometry=new T.BufferGeometry();markerGeometry.setAttribute('position',new T.BufferAttribute(markerPositions,3));
  const markerMaterial=new T.PointsMaterial({color:0x64748b,size:5,sizeAttenuation:false,transparent:true,opacity:.72,depthTest:false});
  markerMaterial.onBeforeCompile=shader=>{shader.fragmentShader=shader.fragmentShader.replace('#include <clipping_planes_fragment>','#include <clipping_planes_fragment>\nif (distance(gl_PointCoord, vec2(0.5)) > 0.5) discard;');};
  const markers=new T.Points(markerGeometry,markerMaterial);markers.frustumCulled=false;markers.renderOrder=10;markers.visible=false;scene.add(markers);
  const hover=document.createElement('div');hover.className='part-hover';hover.setAttribute('role','tooltip');hover.hidden=true;el.appendChild(hover);
  type Target={index:number;x:number;y:number;left:number;right:number;top:number;bottom:number};let targets:Target[]=[];
  const projected=new T.Vector3();
  const findTarget=(x:number,y:number,radius:number)=>{
   let best=-1,score=Infinity;
   for(const t of targets){const dx=Math.max(t.left-x,0,x-t.right),dy=Math.max(t.top-y,0,y-t.bottom),distance=Math.hypot(dx,dy);if(distance>radius)continue;const candidate=distance+Math.hypot(t.x-x,t.y-y)*.025;if(candidate<score){score=candidate;best=t.index;}}
   return best;
  };
  const materialFor=(system:string)=>{
   const m=new T.MeshStandardMaterial({color:SYSTEMS.find(s=>s.id===system)?.color??'#aebbb8',metalness:.08,roughness:.53,side:T.DoubleSide,transparent:system==='integumentary',opacity:system==='integumentary'?.1:1,depthWrite:system!=='integumentary'});
   m.onBeforeCompile=shader=>{
    shader.uniforms.partState={value:partTexture};shader.uniforms.selectionState={value:selectionTexture};shader.uniforms.stateWidth={value:width};
    shader.vertexShader='attribute float partIndex; uniform sampler2D partState; uniform sampler2D selectionState; uniform float stateWidth; varying float partVisible; varying float partSelected;\n'+shader.vertexShader;
    shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\nvec2 stateUv = vec2((partIndex + 0.5) / stateWidth, 0.5); vec4 state = texture2D(partState, stateUv); transformed += state.xyz; partVisible = state.w; partSelected = texture2D(selectionState, stateUv).r;');
    shader.fragmentShader='varying float partVisible; varying float partSelected;\n'+shader.fragmentShader;
    shader.fragmentShader=shader.fragmentShader.replace('#include <clipping_planes_fragment>','#include <clipping_planes_fragment>\nif (partVisible < 0.5) discard;');
    shader.fragmentShader=shader.fragmentShader.replace('#include <color_fragment>','#include <color_fragment>\ndiffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.42, 0.85, 0.78), partSelected * 0.75);');
   };materials.push(m);return m;
  };
  const mats=new Map(SYSTEMS.map(s=>[s.id,materialFor(s.id)]));
  let loaded=0;
  const loadChunk=async(ci:number)=>{
   const chunk=atlas.chunks[ci],compressed=!!chunk.gzip&&typeof DecompressionStream!=='undefined';const response=await fetch(compressed?chunk.gzip!:chunk.url,{signal:abort.signal});const buffer=await decodeModelResponse(response,chunk.bytes,compressed);if(disposed)return;
   const groups=new Map<string,T.BufferGeometry[]>();
   atlas.parts.forEach((p,i)=>{
    if(p.chunk!==ci)return;
    const g=new T.BufferGeometry();g.setAttribute('position',new T.BufferAttribute(new Float32Array(buffer,p.positions,p.vertexCount*3),3));
    // GPU normalized signed-short normals keep the complete atlas compact in memory.
    g.setAttribute('normal',new T.BufferAttribute(new Int16Array(buffer,p.normals,p.vertexCount*3),3,true));g.setIndex(new T.BufferAttribute(new Uint32Array(buffer,p.indices,p.indexCount),1));
    g.boundingBox=bounds[i].clone();g.computeBoundingSphere();const pick=new T.Mesh(g,pickingMaterial);pick.matrixAutoUpdate=false;pickers[i]=pick;geometries.push(g);
    g.setAttribute('partIndex',new T.BufferAttribute(new Float32Array(p.vertexCount).fill(i),1));
    const list=groups.get(p.system)??[];list.push(g);groups.set(p.system,list);
   });
   groups.forEach((gs,system)=>{const geometry=mergeGeometries(gs,false);if(!geometry)throw new Error('Could not assemble anatomy geometry.');geometries.push(geometry);const mesh=new T.Mesh(geometry,mats.get(system as never));mesh.frustumCulled=false;scene.add(mesh);});
   lastState=null;loaded++;onProgress(Math.round(loaded/atlas.chunks.length*100));dirty=true;
  };
  (async()=>{try{let cursor=0;await Promise.all(Array.from({length:3},async()=>{while(cursor<atlas.chunks.length){const i=cursor++;await loadChunk(i);}}));if(!disposed){ready=true;dirty=true;}}catch(e){if(!disposed)onError(e instanceof Error?e.message:'Could not load the anatomy.');}})();
  const frameDimensions=()=>{const w=Math.max(1,el.clientWidth),h=Math.max(1,el.clientHeight),mobile=window.innerWidth<=760,top=mobile?100:60,bottom=mobile?185:200;return {w,h,width:Math.max(120,w-56),height:Math.max(120,h-top-bottom),centerY:(top+h-bottom)/2};};
  const applyFrameOffset=()=>{const {w,h,centerY}=frameDimensions();camera.setViewOffset(w,h,0,h/2-centerY,w,h);};
  const fit=(view:string,extent=0)=>{
   const {w,h,width:availableWidth,height:availableHeight}=frameDimensions();applyFrameOffset();
   const fov=2*Math.tan(T.MathUtils.degToRad(camera.fov/2));
   const normalDistance=Math.max(1.8*h/availableHeight,.8*w/availableWidth/camera.aspect)/fov*1.16;
   const atlasDistance=Math.max(packingHeight*h/availableHeight,packingWidth*w/availableWidth/camera.aspect)/fov*1.08;
   const distance=T.MathUtils.lerp(normalDistance,Math.max(.2,atlasDistance),extent)/Math.max(.1,latest.current.zoom??1);if(extent>.8)view='front';
   const direction=view==='front'?new T.Vector3(0,.02,1):view==='back'?new T.Vector3(0,.02,-1):view==='side'?new T.Vector3(1,.02,0):new T.Vector3(.35,.06,1).normalize();
   controls.maxDistance=Math.max(40,distance*2);controls.target.set(0,.85,0);camera.position.copy(controls.target).addScaledVector(direction,distance);controls.update();dirty=true;
  };
  const resize=()=>{layoutKey='';lastState=null;lastIsolate='';renderer.setPixelRatio(Math.min(devicePixelRatio,el.clientWidth<768||el.clientHeight<600?1.5:2));camera.aspect=Math.max(1,el.clientWidth)/Math.max(1,el.clientHeight);camera.updateProjectionMatrix();renderer.setSize(Math.max(1,el.clientWidth),Math.max(1,el.clientHeight));fit(latest.current.view,amount);};const observer=new ResizeObserver(resize);observer.observe(el);
  const raycaster=new T.Raycaster(),pointer=new T.Vector2(),tap=new PointerTap(),worldBox=new T.Box3(),hitPoint=new T.Vector3();let lastHover=0;
  const pickAt=(x:number,y:number,radius=16)=>{
   if(!ready)return -1;const rect=renderer.domElement.getBoundingClientRect();pointer.set(x/rect.width*2-1,-y/rect.height*2+1);raycaster.setFromCamera(pointer,camera);
   let nearest=Infinity,found=-1;const hasSolid=atlas.parts.some((p,i)=>p.system!=='integumentary'&&data[i*4+3]>.5);
   pickers.forEach((mesh,i)=>{if(!mesh||data[i*4+3]<.5||(hasSolid&&atlas.parts[i].system==='integumentary'))return;worldBox.copy(bounds[i]).translate(mesh.position);if(!raycaster.ray.intersectBox(worldBox,hitPoint))return;const hits=raycaster.intersectObject(mesh,false);if(hits[0]&&hits[0].distance<nearest){nearest=hits[0].distance;found=i;}});
   if(found<0&&amount>.45)found=findTarget(x,y,radius);return found;
  };
  const down=(e:PointerEvent)=>{renderer.domElement.focus({preventScroll:true});hover.hidden=true;tap.down(e.pointerId,e.clientX,e.clientY,e.pointerType==='touch'?12:5);};
  const move=(e:PointerEvent)=>{tap.move(e.pointerId,e.clientX,e.clientY);if(e.buttons||!latest.current.labels||e.pointerType==='touch'){hover.hidden=true;return;}const now=performance.now();if(now-lastHover<100)return;lastHover=now;const rect=el.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top,index=pickAt(x,y,12);hover.hidden=index<0;renderer.domElement.style.cursor=index<0?'grab':'pointer';if(index>=0){hover.textContent=atlas.parts[index].name;hover.style.left=`${Math.max(8,Math.min(x+14,el.clientWidth-260))}px`;hover.style.top=`${Math.max(8,Math.min(y+18,el.clientHeight-55))}px`;}};
  const cancel=(e:PointerEvent)=>{tap.cancel(e.pointerId);hover.hidden=true;};
  const leave=()=>{hover.hidden=true;renderer.domElement.style.cursor='grab';};
  const up=(e:PointerEvent)=>{if(!tap.up(e.pointerId,e.clientX,e.clientY))return;const rect=renderer.domElement.getBoundingClientRect(),found=pickAt(e.clientX-rect.left,e.clientY-rect.top,e.pointerType==='touch'?24:16);if(found>=0){hover.hidden=true;select.current(atlas.parts[found].id);}};
  const keydown=(e:KeyboardEvent)=>{
   if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','_','Home','Enter'].includes(e.key))return;e.preventDefault();hover.hidden=true;
   const offset=camera.position.clone().sub(controls.target);
   if(e.key==='Home'){fit(latest.current.view,amount);lastIsolate='';}
   else if(e.key==='Enter'){const {w,centerY}=frameDimensions(),index=pickAt(w/2,centerY);if(index>=0)select.current(atlas.parts[index].id);}
   else if(e.key==='+'||e.key==='='||e.key==='-'||e.key==='_'){offset.multiplyScalar(e.key==='+'||e.key==='='?.85:1.18);offset.setLength(T.MathUtils.clamp(offset.length(),controls.minDistance,controls.maxDistance));camera.position.copy(controls.target).add(offset);}
   else if(e.shiftKey){const distance=offset.length()*2*Math.tan(T.MathUtils.degToRad(camera.fov/2))*24/Math.max(1,el.clientHeight),horizontal=e.key==='ArrowLeft'||e.key==='ArrowRight',direction=e.key==='ArrowLeft'||e.key==='ArrowDown'?1:-1,pan=new T.Vector3().setFromMatrixColumn(camera.matrixWorld,horizontal?0:1).multiplyScalar(distance*direction);camera.position.add(pan);controls.target.add(pan);}
   else {const spherical=new T.Spherical().setFromVector3(offset);if(e.key==='ArrowLeft')spherical.theta-=.12;if(e.key==='ArrowRight')spherical.theta+=.12;if(e.key==='ArrowUp')spherical.phi-=.09;if(e.key==='ArrowDown')spherical.phi+=.09;spherical.phi=T.MathUtils.clamp(spherical.phi,.03,Math.PI*.96);camera.position.copy(controls.target).add(new T.Vector3().setFromSpherical(spherical));}
   controls.update();dirty=true;
  };
  renderer.domElement.style.cursor='grab';
  renderer.domElement.addEventListener('pointerdown',down);renderer.domElement.addEventListener('pointermove',move);renderer.domElement.addEventListener('pointerup',up);renderer.domElement.addEventListener('pointercancel',cancel);renderer.domElement.addEventListener('pointerleave',leave);renderer.domElement.addEventListener('keydown',keydown);
  const clock=new T.Clock();let lastExtent=-1,lastTheme:''|'light'|'dark'='';
  const animate=()=>{
   if(disposed)return;frame=requestAnimationFrame(animate);const dt=Math.min(clock.getDelta(),.05),s=latest.current;
   if(lastTheme!==latestTheme.current){
    const light=latestTheme.current==='light';
    platform.material.color.set(light?0xd6e1de:0x242830);
    ring.material.color.set(light?0x5b7a73:0x7a8796);ring.material.opacity=light?.4:.25;
    markerMaterial.color.set(light?0x526b65:0x64748b);markerMaterial.opacity=light?.85:.72;
    lastTheme=latestTheme.current;dirty=true;
   }
   const changed=lastState?.visible!==s.visible||lastState?.selected!==s.selected||lastState?.isolate!==s.isolate||lastState?.hidden!==s.hidden;
   if(!s.labels)hover.hidden=true;
   const nextZoom=Math.max(.1,s.zoom??1);if(nextZoom!==lastZoom){camera.position.sub(controls.target).multiplyScalar(lastZoom/nextZoom).add(controls.target);lastZoom=nextZoom;controls.update();dirty=true;}
   const opacity=T.MathUtils.clamp(s.opacity??1,.05,1);if(opacity!==lastOpacity){mats.forEach((m,system)=>{m.opacity=opacity*(system==='integumentary'?.1:1);m.transparent=m.opacity<1;m.depthWrite=m.opacity>=1;m.needsUpdate=true;});lastOpacity=opacity;dirty=true;}
   // A newly explored structure starts assembled; reassembly of the same
   // selection still animates back smoothly.
   if(lastState&&lastState.selected!==s.selected&&s.explode===0)amount=0;
   const moving=Math.abs(amount-s.explode)>.0001;
   if(moving){amount=T.MathUtils.damp(amount,s.explode,8,dt);dirty=true;}
   if(changed||moving||lastExtent<0){
    const visible=new Set(s.visible),selection=new Set(s.selected),hidden=new Set(s.hidden??[]);
    const visibleParts=atlas.parts.filter(p=>!hidden.has(p.id)&&(s.isolate?selection.has(p.id):visible.has(p.system)||selection.has(p.id)));
    const nextLayoutKey=visibleParts.map(p=>p.id).join(',')+':'+camera.aspect.toFixed(3);
    if(nextLayoutKey!==layoutKey){const layout=createExplosionLayout(visibleParts,camera.aspect);packingWidth=layout.width;packingHeight=layout.height;atlas.parts.forEach((p,i)=>{const cell=layout.cells.get(p.id);offsets[i]=cell?new T.Vector3(cell.x,cell.y+.85,0):centers[i].clone();});layoutKey=nextLayoutKey;if(amount>.05&&!s.isolate)fit(s.view,Math.max(0,(amount-.3)/.7));}

    atlas.parts.forEach((p,i)=>{
     const c=centers[i],destination=offsets[i];let dx=0,dy=0,dz=0;
     // Within a selected structure, separate its individual pieces immediately
     // instead of first moving the entire anatomical system as one group.
     if(s.isolate){dx=(destination.x-c.x)*amount;dy=(destination.y-c.y)*amount;dz=-c.z*amount;}
     else if(amount<=.45){const t=amount/.45;const group=SYSTEMS.findIndex(sys=>sys.id===p.system);const angle=group/SYSTEMS.length*Math.PI*2;dx=Math.sin(angle)*t*.48;dy=(c.y-.85)*t*.28;dz=Math.cos(angle)*t*.48;}
     else {const t=(amount-.45)/.55,group=SYSTEMS.findIndex(sys=>sys.id===p.system),angle=group/SYSTEMS.length*Math.PI*2;dx=T.MathUtils.lerp(Math.sin(angle)*.48,destination.x-c.x,t);dy=T.MathUtils.lerp((c.y-.85)*.28,destination.y-c.y,t);dz=T.MathUtils.lerp(Math.cos(angle)*.48,-c.z,t);}
     const selected=selection.has(p.id);data.set([dx,dy,dz,(!hidden.has(p.id)&&(s.isolate?selected:visible.has(p.system)||selected))?1:0],i*4);selectedData[i*4]=selected?255:0;
     markerPositions.set(data[i*4+3]>.5?[c.x+dx,c.y+dy,c.z+dz]:[10000,10000,10000],i*3);const mesh=pickers[i];if(mesh){mesh.position.set(dx,dy,dz);mesh.updateMatrix();mesh.updateMatrixWorld(true);}
    });partTexture.needsUpdate=true;selectionTexture.needsUpdate=true;markerGeometry.attributes.position.needsUpdate=true;lastState=s;lastExtent=amount;dirty=true;
   }
   if(s.view!==lastView||s.reset!==lastReset){fit(s.view,amount);lastView=s.view;lastReset=s.reset;}
   if(moving&&!s.isolate)fit(amount>.5?'front':s.view,Math.max(0,(amount-.3)/.7));
   const isolateKey=s.isolate?s.selected.join(',')+':'+s.reset+':'+s.view+':'+s.hidden?.join(',')+':'+camera.aspect:'';
   if(isolateKey!==lastIsolate||(s.isolate&&moving)){
    if(s.isolate){const box=new T.Box3();atlas.parts.forEach((p,i)=>{if(s.selected.includes(p.id)&&!s.hidden?.includes(p.id))box.union(bounds[i].clone().translate(new T.Vector3(data[i*4],data[i*4+1],data[i*4+2])));});
     if(!box.isEmpty()){const center=box.getCenter(new T.Vector3()),size=box.getSize(new T.Vector3()),{w,h,width:availableWidth,height:availableHeight}=frameDimensions();applyFrameOffset();const distance=Math.max(.07,Math.max(size.y*h/availableHeight,size.x*w/availableWidth/camera.aspect,size.z)/(2*Math.tan(T.MathUtils.degToRad(camera.fov/2)))*1.2/Math.max(.1,s.zoom??1));controls.maxDistance=Math.max(40,distance*2);const direction=s.view==='front'?new T.Vector3(0,.02,1):s.view==='back'?new T.Vector3(0,.02,-1):s.view==='side'?new T.Vector3(1,.02,0):new T.Vector3(.25,.08,1).normalize();controls.target.copy(center);camera.position.copy(center).addScaledVector(direction,distance);controls.update();dirty=true;}
    }else if(lastIsolate){fit(s.view,amount);}
    lastIsolate=isolateKey;
   }
   controls.enableRotate=amount<.8;controls.mouseButtons.LEFT=amount<.8?T.MOUSE.ROTATE:T.MOUSE.PAN;controls.touches.ONE=amount<.8?T.TOUCH.ROTATE:T.TOUCH.PAN;platform.visible=ring.visible=amount<.5&&!s.isolate;markers.visible=amount>.75;controls.autoRotate=s.rotate&&!s.isolate&&amount<.4;controls.autoRotateSpeed=.65;controls.update();if(controls.autoRotate)dirty=true;
   if(dirty){renderer.render(scene,camera);targets=[];if(amount>.45){const hasSolid=atlas.parts.some((p,i)=>p.system!=='integumentary'&&data[i*4+3]>.5);atlas.parts.forEach((p,i)=>{if(data[i*4+3]<.5||(hasSolid&&p.system==='integumentary'))return;let left=Infinity,right=-Infinity,top=Infinity,bottom=-Infinity;for(let corner=0;corner<8;corner++){projected.set(p.bounds[(corner&1)?1:0][0]+data[i*4],p.bounds[(corner&2)?1:0][1]+data[i*4+1],p.bounds[(corner&4)?1:0][2]+data[i*4+2]).project(camera);const x=(projected.x+1)*el.clientWidth/2,y=(1-projected.y)*el.clientHeight/2;left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}projected.copy(centers[i]).add(new T.Vector3(data[i*4],data[i*4+1],data[i*4+2])).project(camera);if(projected.z< -1||projected.z>1)return;targets.push({index:i,x:(projected.x+1)*el.clientWidth/2,y:(1-projected.y)*el.clientHeight/2,left,right,top,bottom});});}dirty=false;}

  };animate();
  const contextLost=(e:Event)=>{e.preventDefault();onError('The 3D session was paused by your device. Reload to continue.');};renderer.domElement.addEventListener('webglcontextlost',contextLost);
  return()=>{disposed=true;abort.abort();cancelAnimationFrame(frame);observer.disconnect();renderer.domElement.removeEventListener('pointerdown',down);renderer.domElement.removeEventListener('pointermove',move);renderer.domElement.removeEventListener('pointerup',up);renderer.domElement.removeEventListener('pointercancel',cancel);renderer.domElement.removeEventListener('pointerleave',leave);renderer.domElement.removeEventListener('keydown',keydown);renderer.domElement.removeEventListener('webglcontextlost',contextLost);controls.dispose();geometries.forEach(g=>g.dispose());materials.forEach(m=>m.dispose());pickingMaterial.dispose();scene.traverse(o=>{if(o instanceof T.Mesh&&!geometries.includes(o.geometry)){o.geometry.dispose();const ms=Array.isArray(o.material)?o.material:[o.material];ms.forEach(m=>m.dispose());}});env.dispose();partTexture.dispose();selectionTexture.dispose();markerGeometry.dispose();markerMaterial.dispose();hover.remove();renderer.dispose();renderer.domElement.remove();};
 },[atlas]);
 return <div className="scene" ref={host}/>;
}

import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { useReducedMotion } from 'motion/react';

export default function Scene({ paused = false, mode = 'auth', nodeStates = '1,1', dark = false }) {
  const host = useRef(null),
    [ready, setReady] = useState(false),
    reduced = useReducedMotion();
  useEffect(() => {
    const el = host.current;
    let renderer,
      environment,
      frame = 0,
      observer,
      resizeObserver,
      active = true,
      disposed = false;
    const scene = new THREE.Scene(),
      group = new THREE.Group();
    scene.add(group);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 80);
    const geometries = [],
      materials = [];
    const geometry = (g) => {
      geometries.push(g);
      return g;
    };
    const material = (m) => {
      materials.push(m);
      return m;
    };
    const metal = material(
      new THREE.MeshStandardMaterial({
        color: dark ? 0x929caa : 0xb4b8c3,
        metalness: 1,
        roughness: 0.16,
        envMapIntensity: 0.85,
      }),
    );
    const red = material(
      new THREE.MeshPhysicalMaterial({
        color: 0xe84536,
        metalness: 0.3,
        roughness: 0.25,
        clearcoat: 1,
        clearcoatRoughness: 0.2,
      }),
    );
    const blue = material(
      new THREE.MeshStandardMaterial({ color: 0x3956b9, metalness: 0.4, roughness: 0.3 }),
    );
    const porcelain = material(
      new THREE.MeshStandardMaterial({
        color: dark ? 0x42454a : 0xf5f5f2,
        metalness: 0.12,
        roughness: 0.25,
      }),
    );
    const inactive = material(
      new THREE.MeshStandardMaterial({ color: 0x696c75, metalness: 0.3, roughness: 0.5 }),
    );
    const cables = [],
      packets = [];
    const pointer = { x: 0, y: 0 };
    let inView = true,
      last = 0,
      elapsed = 0;
    function mesh(g, m, pos, scale) {
      const object = new THREE.Mesh(g, m);
      if (pos) object.position.copy(pos);
      if (scale) object.scale.setScalar(scale);
      group.add(object);
      return object;
    }
    try {
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: 'low-power',
        preserveDrawingBuffer: true,
      });
      renderer.setPixelRatio(Math.min(devicePixelRatio, innerWidth < 760 ? 1 : 1.5));
      renderer.setClearColor(0x000000, 0);
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1;
      el.append(renderer.domElement);
      const room = new RoomEnvironment(),
        pmrem = new THREE.PMREMGenerator(renderer);
      environment = pmrem.fromScene(room, 0.04);
      scene.environment = environment.texture;
      room.dispose();
      pmrem.dispose();
      const light = new THREE.DirectionalLight(0xffffff, 2);
      light.position.set(-3, 5, 5);
      scene.add(light);
      const fill = new THREE.DirectionalLight(0xb2c6ff, 1.4);
      fill.position.set(4, -2, 3);
      scene.add(fill);
      const states =
        mode === 'auth' ? [1, 1, 1] : nodeStates.split(',').filter(Boolean).map(Number).slice(0, 5);
      const count = states.length;
      const box = geometry(new RoundedBoxGeometry(0.75, 0.75, 0.75, 3, 0.13));
      const hub = mesh(box, red, new THREE.Vector3(-1.8, -0.25, 0.2), 1.22);
      hub.rotation.set(0.15, 0.35, 0.2);
      for (let i = 0; i < count; i++) {
        const a = (i / count) * Math.PI * 2 - 0.6;
        const end = new THREE.Vector3(
          1.25 + Math.cos(a) * 1.12,
          Math.sin(a) * 1.15,
          Math.cos(a * 2) * 0.48,
        );
        const node = mesh(box, states[i] ? (i % 2 === 0 ? porcelain : blue) : inactive, end, 0.85);
        node.rotation.set(0.22, 0.3, -0.2);
        const curve = new THREE.CatmullRomCurve3([
          hub.position.clone(),
          new THREE.Vector3(-0.8, -1.65 - i * 0.2, 1),
          new THREE.Vector3(0.2, 1.35 + i * 0.28, 0.5),
          end,
        ]);
        const tube = geometry(new THREE.TubeGeometry(curve, 84, 0.115, 10, false));
        mesh(tube, metal);
        cables.push(curve);
        const packet = mesh(geometry(new RoundedBoxGeometry(0.18, 0.18, 0.32, 1, 0.035)), red);
        packet.visible = Boolean(states[i]);
        packets.push(packet);
      }
      group.rotation.set(-0.15, -0.2, -0.14);
      function resize() {
        if (disposed) return;
        const { width, height } = el.getBoundingClientRect();
        if (!width || !height) return;
        renderer.setSize(width, height);
        camera.aspect = width / height;
        const mobile = width < 760;
        const distance =
          mode === 'auth' ? (mobile ? Math.max(21, 5.8 / (0.689 * camera.aspect)) : 11.5) : 6.5;
        camera.position.set(0, 0, distance);
        camera.lookAt(0, 0, 0);
        camera.updateProjectionMatrix();
        group.position.set(
          mode === 'auth' ? (mobile ? -0.25 : -1.65) : 0,
          mode === 'auth' && mobile ? distance * 0.19 : 0,
          0,
        );
        draw(elapsed);
      }
      function draw(t) {
        if (disposed) return;
        group.rotation.y = -0.2 + pointer.x * 0.15;
        group.rotation.x = -0.15 + pointer.y * 0.08;
        group.rotation.z = -0.14 + (paused || reduced ? 0 : Math.sin(t * 0.22) * 0.035);
        packets.forEach((packet, i) => {
          const f = (t * 0.09 + i * 0.24) % 1;
          packet.position.copy(cables[i].getPointAt(f));
          packet.quaternion.setFromUnitVectors(
            new THREE.Vector3(0, 0, 1),
            cables[i].getTangentAt(f).normalize(),
          );
        });
        renderer.render(scene, camera);
      }
      function tick(time) {
        if (disposed) return;
        frame = 0;
        if (!active || !inView || document.hidden) return;
        if (time - last >= 33) {
          elapsed += time - last < 200 ? (time - last) / 1000 : 0.033;
          last = time;
          draw(elapsed);
        }
        frame = requestAnimationFrame(tick);
      }
      const start = () => {
        if (!frame && active && inView && !document.hidden && !disposed) {
          last = performance.now();
          frame = requestAnimationFrame(tick);
        }
      };
      const stop = () => {
        cancelAnimationFrame(frame);
        frame = 0;
      };
      function move(event) {
        const rect = el.getBoundingClientRect();
        pointer.x = (event.clientX - rect.left) / rect.width - 0.5;
        pointer.y = (event.clientY - rect.top) / rect.height - 0.5;
        if (!active) draw(elapsed);
      }
      function visibility() {
        if (document.hidden) stop();
        else start();
      }
      function lost(event) {
        event.preventDefault();
        stop();
        setReady(false);
      }
      active = !paused && !reduced;
      resize();
      setReady(true);
      start();
      observer = new IntersectionObserver((entries) => {
        inView = entries[0].isIntersecting;
        if (inView) start();
        else stop();
      });
      observer.observe(el);
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(el);
      el.addEventListener('pointermove', move);
      document.addEventListener('visibilitychange', visibility);
      renderer.domElement.addEventListener('webglcontextlost', lost);
      return () => {
        disposed = true;
        stop();
        observer.disconnect();
        resizeObserver.disconnect();
        el.removeEventListener('pointermove', move);
        document.removeEventListener('visibilitychange', visibility);
        renderer.domElement.removeEventListener('webglcontextlost', lost);
        geometries.forEach((g) => g.dispose());
        materials.forEach((m) => m.dispose());
        environment.dispose();
        renderer.dispose();
        renderer.domElement.remove();
      };
    } catch {
      setReady(false);
      cancelAnimationFrame(frame);
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.dispose());
      environment?.dispose();
      renderer?.dispose();
      renderer?.domElement.remove();
    }
  }, [paused, reduced, mode, nodeStates, dark]);
  return (
    <div
      ref={host}
      className={'connection-scene scene-' + mode + (ready ? ' ready' : '')}
      aria-hidden="true"
    >
      <img className="scene-fallback" src="/assets/edge-glass.webp" alt="" />
    </div>
  );
}

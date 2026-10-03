import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { useReducedMotion } from 'motion/react';
import { connections, TUBE_RADIUS, COLLAR_INNER_RADIUS } from './scene-model';
import SceneFallback from './SceneFallback';

export default function Scene({ mode = 'auth', nodeStates = '1,1', dark = false }) {
  const host = useRef(null),
    rotation = useRef(-0.35);
  const [ready, setReady] = useState(false),
    [failed, setFailed] = useState(false);
  const reduced = useReducedMotion();
  useEffect(() => {
    const el = host.current;
    let renderer,
      environment,
      observer,
      resizeObserver,
      frame = 0,
      disposed = false,
      available = true;
    let inView = true,
      last = 0,
      elapsed = 0,
      drag = null;
    const scene = new THREE.Scene(),
      group = new THREE.Group();
    scene.add(group);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 80);
    const geometries = [],
      materials = [],
      packets = [];
    const geometry = (g) => {
      geometries.push(g);
      return g;
    };
    const material = (m) => {
      materials.push(m);
      return m;
    };
    const mesh = (g, m, position, parent = group) => {
      const object = new THREE.Mesh(g, m);
      if (position) object.position.copy(position);
      parent.add(object);
      return object;
    };
    const dispose = () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer?.disconnect();
      resizeObserver?.disconnect();
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.dispose());
      environment?.dispose();
      renderer?.dispose();
      renderer?.domElement.remove();
    };
    setReady(false);
    setFailed(false);
    try {
      renderer = new THREE.WebGLRenderer({
        alpha: false,
        antialias: true,
        powerPreference: 'low-power',
        preserveDrawingBuffer: true,
      });
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 0.95;
      // Match the enclosing surface so transmission sees a real background, not black alpha.
      scene.background = new THREE.Color(getComputedStyle(el.parentElement).backgroundColor);
      el.append(renderer.domElement);
      const room = new RoomEnvironment(),
        pmrem = new THREE.PMREMGenerator(renderer);
      environment = pmrem.fromScene(room, 0.015);
      scene.environment = environment.texture;
      room.dispose();
      pmrem.dispose();
      const key = new THREE.DirectionalLight(0xffffff, 2.5);
      key.position.set(-3, 5, 4);
      scene.add(key);
      const fill = new THREE.DirectionalLight(0xd6e4ff, 1.5);
      fill.position.set(4, 1, -4);
      scene.add(fill);
      const chrome = material(
        new THREE.MeshStandardMaterial({
          color: 0xc3c7cf,
          metalness: 1,
          roughness: 0.085,
          envMapIntensity: 1.3,
        }),
      );
      const rubyMetal = material(
        new THREE.MeshStandardMaterial({
          color: 0xc9271b,
          metalness: 0.85,
          roughness: 0.12,
          envMapIntensity: 1.5,
        }),
      );
      const crystal = (color, thickness = 0.6) =>
        material(
          new THREE.MeshPhysicalMaterial({
            color: 0xffffff,
            metalness: 0,
            roughness: 0.045,
            transmission: 0.96,
            thickness,
            ior: 1.52,
            attenuationColor: new THREE.Color(color),
            attenuationDistance: 0.8,
            clearcoat: 1,
            clearcoatRoughness: 0.04,
            envMapIntensity: 1.6,
          }),
        );
      const ruby = crystal(0xff5344, 0.8),
        sapphire = crystal(0x5279ff),
        clear = crystal(0xd7edf8);
      const inactive = material(
        new THREE.MeshStandardMaterial({ color: 0x737982, metalness: 0.85, roughness: 0.2 }),
      );
      const states =
        mode === 'auth' ? [1, 1, 1] : nodeStates.split(',').filter(Boolean).map(Number).slice(0, 5);
      const links = connections(states.length);
      const hub = new THREE.Group();
      hub.position.set(-1.65, 0, 0);
      group.add(hub);
      mesh(geometry(new RoundedBoxGeometry(1.08, 1.36, 0.84, 4, 0.07)), ruby, null, hub);
      mesh(
        geometry(new RoundedBoxGeometry(0.78, 1.05, 0.25, 3, 0.035)),
        rubyMetal,
        new THREE.Vector3(0, 0, 0),
        hub,
      );
      const box = geometry(new RoundedBoxGeometry(0.67, 0.67, 0.67, 4, 0.045));
      const core = geometry(new RoundedBoxGeometry(0.42, 0.42, 0.18, 3, 0.025));
      const ring = geometry(new THREE.TorusGeometry(COLLAR_INNER_RADIUS + 0.028, 0.028, 12, 32));
      links.forEach((link, i) => {
        const node = new THREE.Group();
        node.position.copy(link.end).add(new THREE.Vector3(0.34, 0, 0));
        group.add(node);
        mesh(box, states[i] ? (i % 2 ? sapphire : clear) : inactive, null, node);
        mesh(core, chrome, null, node);
        mesh(geometry(new THREE.TubeGeometry(link.curve, 112, TUBE_RADIUS, 18, false)), chrome);
        const packet = mesh(ring, rubyMetal);
        packet.visible = Boolean(states[i]);
        packets.push(packet);
      });
      const tangentAxis = new THREE.Vector3(0, 0, 1);
      function draw() {
        if (disposed || !available) return;
        group.rotation.set(-0.13, rotation.current, -0.08);
        packets.forEach((packet, i) => {
          const fraction = 0.12 + ((elapsed * 0.1 + i * 0.27) % 1) * 0.76;
          packet.position.copy(links[i].curve.getPointAt(fraction));
          packet.quaternion.setFromUnitVectors(
            tangentAxis,
            links[i].curve.getTangentAt(fraction).normalize(),
          );
        });
        renderer.render(scene, camera);
        el.dataset.rotation = rotation.current.toFixed(5);
      }
      function resize() {
        if (disposed) return;
        const { width, height } = el.getBoundingClientRect();
        if (!width || !height) return;
        renderer.setPixelRatio(
          Math.min(devicePixelRatio || 1, 2, Math.sqrt(4_000_000 / (width * height))),
        );
        renderer.setSize(width, height);
        camera.aspect = width / height;
        const mobile = width < 760;
        const distance =
          mode === 'auth' ? (mobile ? Math.max(7.8, 5.8 / (0.689 * camera.aspect)) : 11.5) : 6.8;
        camera.position.set(0, 0, distance);
        camera.lookAt(0, 0, 0);
        camera.updateProjectionMatrix();
        group.position.set(mode === 'auth' && !mobile ? -1.65 : 0, 0, 0);
        draw();
      }
      function tick(time) {
        frame = 0;
        if (disposed || !available || reduced || !inView || document.hidden) return;
        if (time - last >= 33) {
          const delta = Math.min((time - last) / 1000, 0.1);
          last = time;
          elapsed += delta;
          if (!drag) rotation.current -= delta * 0.07;
          draw();
        }
        frame = requestAnimationFrame(tick);
      }
      function start() {
        if (!frame && !disposed && available && !reduced && inView && !document.hidden) {
          last = performance.now();
          frame = requestAnimationFrame(tick);
        }
      }
      function stop() {
        cancelAnimationFrame(frame);
        frame = 0;
      }
      function down(event) {
        if (event.button !== 0 || !event.isPrimary) return;
        drag = { id: event.pointerId, x: event.clientX, angle: rotation.current };
        renderer.domElement.setPointerCapture(event.pointerId);
        el.classList.add('dragging');
      }
      function move(event) {
        if (!drag || drag.id !== event.pointerId) return;
        rotation.current = drag.angle + (event.clientX - drag.x) * 0.009;
        draw();
      }
      function up(event) {
        if (!drag || drag.id !== event.pointerId) return;
        drag = null;
        el.classList.remove('dragging');
        if (renderer.domElement.hasPointerCapture(event.pointerId))
          renderer.domElement.releasePointerCapture(event.pointerId);
      }
      function visibility() {
        if (document.hidden) {
          drag = null;
          el.classList.remove('dragging');
          stop();
        } else start();
      }
      function lost(event) {
        event.preventDefault();
        available = false;
        drag = null;
        el.classList.remove('dragging');
        stop();
        setReady(false);
        setFailed(true);
      }
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
      const canvas = renderer.domElement;
      canvas.addEventListener('pointerdown', down);
      canvas.addEventListener('pointermove', move);
      canvas.addEventListener('pointerup', up);
      canvas.addEventListener('pointercancel', up);
      canvas.addEventListener('lostpointercapture', up);
      canvas.addEventListener('webglcontextlost', lost);
      document.addEventListener('visibilitychange', visibility);
      return () => {
        canvas.removeEventListener('pointerdown', down);
        canvas.removeEventListener('pointermove', move);
        canvas.removeEventListener('pointerup', up);
        canvas.removeEventListener('pointercancel', up);
        canvas.removeEventListener('lostpointercapture', up);
        canvas.removeEventListener('webglcontextlost', lost);
        document.removeEventListener('visibilitychange', visibility);
        el.classList.remove('dragging');
        dispose();
      };
    } catch {
      setFailed(true);
      dispose();
    }
  }, [reduced, mode, nodeStates, dark]);
  return (
    <div
      ref={host}
      className={'connection-scene scene-' + mode + (ready ? ' ready' : '')}
      aria-hidden="true"
    >
      {failed && <SceneFallback mode={mode} nodeStates={nodeStates} />}
    </div>
  );
}

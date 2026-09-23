/**
 * 饮食助手互动小人「橘子人」—— 3D 形象。
 *
 * 为什么是程序化建模，而不是导入一个 .glb：
 *   1. 仓库只需多带一个 670KB 的 three.js（已内联、不走 CDN），不必再背模型文件与授权；
 *   2. 设定稿（docs/design/diet-assistant-mascot-sheet.png）给的是三视图 + 配色方案 +
 *      身体比例（圆滚滚、高≈宽），球身 + 灰风镜 + 绿十字这个结构用几何体就能精确还原；
 *   3. 「idle ↔ 思考中」两种状态要在**同一个场景里连续过渡** —— 换图片做不到衔接流畅，
 *      只会看到一帧跳变。这里所有动画量都由同一个阻尼系数驱动（见 animate()）。
 *
 * 降级策略：WebGL 不可用、three.js 加载失败或上下文丢失时，本模块保持不生效，
 *   页面继续显示二维的 assets/mascot.png（<img class="mascot-img">）。
 *   那个 <img> 同时也是 core/tests/test_web_assets.py 的依赖，不能删。
 *
 * 与页面的状态约定：经典脚本只写 window.TA_MASCOT.mode（'idle' | 'thinking'），
 *   本模块每帧读它。用一个普通全局对象而不是回调，是为了避免
 *   「模块是 deferred 的，经典脚本跑的时候它还没执行」这类时序问题。
 */

import * as THREE from './three.module.min.js';

// 配色直接取自设定稿的「配色方案」五色，不在别处再定义一套。
const PALETTE = {
  peel: 0xf5851f,      // 橘橙
  peelDark: 0xe2620f,  // 果皮深色
  lens: 0x8e8e8e,      // 镜片灰
  mask: 0xfdfcf9,      // 面罩白
  leaf: 0x1e7a3c,      // 叶绿
  stem: 0x2e7d32,
  ink: 0x242424,
};

const TAU = Math.PI * 2;
const PHI_FRONT = Math.PI / 2; // 该球面参数化下 phi = π/2 指向 +Z（正脸朝向）

/** 球面上一点的单位方向（three.js SphereGeometry 的参数化）。 */
function dirAt(phi, theta) {
  return new THREE.Vector3(
    -Math.cos(phi) * Math.sin(theta),
    Math.cos(theta),
    Math.sin(phi) * Math.sin(theta),
  );
}

/**
 * 朝外贴在球面上的一块蒙皮/附件：给定球面坐标，生成朝向法线的网格。
 * `lookAt` 以世界 +Y 为 up，因此正面区域得到的局部 Y 恒为「大致朝上」，
 * 后续在局部坐标里做眨眼、转笑脸都不需要再算基。
 */
function onSurface(mesh, phi, theta, radius) {
  const dir = dirAt(phi, theta);
  mesh.position.copy(dir).multiplyScalar(radius);
  mesh.lookAt(dir.multiplyScalar(radius * 3));
  return mesh;
}

/** 果皮凹点：bump 用中性灰打底，凹处压暗 —— 这是「橘子皮」质感的全部来源。 */
function makePeelBump() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#808080';
  ctx.fillRect(0, 0, size, size);
  for (let i = 0; i < 900; i++) {
    const x = Math.random() * size;
    const y = Math.random() * size;
    const r = 1.6 + Math.random() * 2.6;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, 'rgba(70,70,70,0.85)');
    g.addColorStop(0.65, 'rgba(128,128,128,0.35)');
    g.addColorStop(1, 'rgba(160,160,160,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.fill();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(3, 2);
  return tex;
}

/** 果皮底色：橘橙打底 + 果皮深色斑驳，避免大面积纯色看起来像塑料球。 */
function makePeelColor() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#f5851f';
  ctx.fillRect(0, 0, size, size);
  for (let i = 0; i < 260; i++) {
    const x = Math.random() * size;
    const y = Math.random() * size;
    const r = 6 + Math.random() * 16;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, 'rgba(226,98,15,0.22)');
    g.addColorStop(1, 'rgba(226,98,15,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, TAU);
    ctx.fill();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(2, 1.4);
  return tex;
}

/** 假投影：径向渐变贴片，比开阴影贴图便宜，且在透明背景上效果一致。 */
function makeShadowTexture() {
  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(0,0,0,0.55)');
  g.addColorStop(0.55, 'rgba(0,0,0,0.22)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** 按设定稿拼出角色，返回 { root, eyes }。root 用于整体缩放（入场），内部各部件自行动。 */
function buildCharacter() {
  const bump = makePeelBump();
  const peelMat = new THREE.MeshStandardMaterial({
    map: makePeelColor(),
    bumpMap: bump,
    bumpScale: 0.9,
    color: 0xffffff,
    roughness: 0.62,
    metalness: 0.0,
  });
  const limbMat = new THREE.MeshStandardMaterial({
    color: PALETTE.peel,
    bumpMap: bump,
    bumpScale: 0.6,
    roughness: 0.66,
  });
  const maskMat = new THREE.MeshStandardMaterial({
    color: PALETTE.mask,
    roughness: 0.5,
    metalness: 0.0,
  });
  const lensMat = new THREE.MeshStandardMaterial({
    color: PALETTE.lens,
    roughness: 0.34,
    metalness: 0.05,
  });
  const leafMat = new THREE.MeshStandardMaterial({
    color: PALETTE.leaf,
    roughness: 0.55,
  });
  const inkMat = new THREE.MeshStandardMaterial({
    color: PALETTE.ink,
    roughness: 0.3,
  });

  const model = new THREE.Group();

  // 身体：设定稿写「圆滚滚橘子形，高≈宽，比例约 1.1:1」⇒ 直接用球，末尾整体压 3%。
  const body = new THREE.Mesh(new THREE.SphereGeometry(1, 64, 48), peelMat);
  model.add(body);

  // 白色面罩（下缘），比风镜更宽一圈 ⇒ 形成设定稿里的「白色面罩下缘」包边。
  const white = new THREE.Mesh(
    new THREE.SphereGeometry(1.012, 48, 32, PHI_FRONT - 0.72, 1.44, 1.60, 0.66),
    maskMat,
  );
  model.add(white);

  // 灰色风镜：叠在白面罩之上（半径更大），风镜外轮廓用橙色包边靠 body 露出。
  const goggle = new THREE.Mesh(
    new THREE.SphereGeometry(1.024, 48, 32, PHI_FRONT - 0.56, 1.12, 1.14, 0.58),
    lensMat,
  );
  model.add(goggle);

  // 眼睛：贴在风镜上，白点是高光。眨眼只缩放局部 Y（lookAt 后局部 Y ≈ 朝上）。
  const eyeGeo = new THREE.CircleGeometry(0.15, 28);
  const glintGeo = new THREE.CircleGeometry(0.048, 16);
  const eyes = [];
  for (const side of [-1, 1]) {
    const eye = new THREE.Mesh(eyeGeo, inkMat);
    onSurface(eye, PHI_FRONT + side * 0.3, 1.44, 1.038);
    const glint = new THREE.Mesh(glintGeo, maskMat);
    onSurface(glint, PHI_FRONT + side * 0.3 - 0.07, 1.375, 1.05);
    model.add(eye, glint);
    eyes.push(eye);
  }

  // 微笑：半环，转 π 让开口朝上成 ∪。
  const smile = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.021, 8, 40, Math.PI), inkMat);
  smile.rotation.z = Math.PI;
  onSurface(smile, PHI_FRONT, 1.96, 1.02);
  model.add(smile);

  // 胸前绿十字：两块薄盒，lookAt 后局部 Z 即法线方向，厚度朝外。
  const crossMat = new THREE.MeshStandardMaterial({ color: PALETTE.leaf, roughness: 0.5 });
  const cross = new THREE.Group();
  cross.add(new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.105, 0.05), crossMat));
  cross.add(new THREE.Mesh(new THREE.BoxGeometry(0.105, 0.34, 0.05), crossMat));
  onSurface(cross, PHI_FRONT, 2.14, 1.02);
  model.add(cross);

  // 四肢：设定稿是短粗的水滴形，用压扁拉长的球近似。
  const armGeo = new THREE.SphereGeometry(0.2, 24, 16);
  for (const side of [-1, 1]) {
    const arm = new THREE.Mesh(armGeo, limbMat);
    arm.scale.set(0.85, 1.35, 0.85);
    arm.position.set(side * 0.93, -0.12, 0.1);
    arm.rotation.z = side * 0.5;
    model.add(arm);
  }
  const legGeo = new THREE.SphereGeometry(0.19, 24, 16);
  for (const side of [-1, 1]) {
    const leg = new THREE.Mesh(legGeo, limbMat);
    leg.scale.set(0.9, 1.2, 0.9);
    leg.position.set(side * 0.34, -0.95, 0.12);
    model.add(leg);
  }

  // 果蒂 + 两片叶子。
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.045, 0.062, 0.24, 14), leafMat);
  stem.position.set(0, 1.06, 0);
  stem.rotation.z = 0.1;
  model.add(stem);
  const leafGeo = new THREE.SphereGeometry(0.17, 22, 14);
  for (const side of [-1, 1]) {
    const leaf = new THREE.Mesh(leafGeo, leafMat);
    leaf.scale.set(1.0, 0.3, 0.62);
    leaf.position.set(side * 0.15, 1.2, 0.02);
    leaf.rotation.set(0, side * 0.5, side * 0.62);
    model.add(leaf);
  }

  model.scale.y = 0.97; // 高≈宽但略压，贴设定稿的 1.1:1
  return { model, eyes };
}

function init() {
  const stage = document.getElementById('mascotStage');
  const canvas = document.getElementById('mascotCanvas');
  const dock = document.getElementById('mascotDock');
  const fallbackImg = document.querySelector('.mascot-img');
  if (!stage || !canvas || !dock || !fallbackImg) return;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  } catch (err) {
    console.warn('[mascot3d] 无 WebGL，继续用二维图：', err);
    return;
  }
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 96 / 132, 0.1, 50);
  camera.position.set(0, 0.1, 6.2);
  camera.lookAt(0, 0.05, 0);

  scene.add(new THREE.HemisphereLight(0xfff6e8, 0xd8cbb6, 0.85));
  const key = new THREE.DirectionalLight(0xffffff, 1.25);
  key.position.set(2.6, 4.2, 3.4);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffe6c4, 0.4);
  fill.position.set(-3.2, 1.2, 2.2);
  scene.add(fill);

  const root = new THREE.Group();
  const { model, eyes } = buildCharacter();
  root.add(model);

  const shadow = new THREE.Mesh(
    new THREE.PlaneGeometry(2.5, 2.5),
    new THREE.MeshBasicMaterial({
      map: makeShadowTexture(),
      transparent: true,
      opacity: 0.5,
      depthWrite: false,
    }),
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = -1.26;
  root.add(shadow);
  scene.add(root);

  // —— 状态：全部由下面这个阻尼系数驱动，因此 idle↔思考 是连续过渡，不会跳变 ——
  const reduceMotion = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let blend = 0;    // 0 = 待机，1 = 思考中
  let spin = 0;     // 思考时累计的转角；回待机时被拉回最近整圈，确保停在正脸
  let appear = 0;   // 入场 0→1
  let t = 0;
  let blinkIn = 2.5;
  let blinkLeft = 0;
  let running = true;

  const page = window.TA_MASCOT || (window.TA_MASCOT = { mode: 'idle' });

  function resize() {
    const w = stage.clientWidth || 96;
    const h = stage.clientHeight || 132;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(resize).observe(stage);
  }
  window.addEventListener('resize', resize);
  resize();

  canvas.addEventListener('webglcontextlost', (event) => {
    // 上下文丢了就退回二维图，不能留一个黑块在那儿
    event.preventDefault();
    running = false;
    stage.hidden = true;
    fallbackImg.hidden = false;
  });

  // 页面用 hidden 属性控制小人出现；隐藏时不渲染，省电。
  if (typeof MutationObserver !== 'undefined') {
    new MutationObserver(() => {
      if (!dock.hidden) resize();
    }).observe(dock, { attributes: true, attributeFilter: ['hidden'] });
  }

  const clock = new THREE.Clock();

  function animate() {
    requestAnimationFrame(animate);
    if (!running) return;
    const dt = Math.min(clock.getDelta(), 0.05); // 切后台回来时 dt 会很大，截断避免瞬移
    if (dock.hidden) return;

    t += dt;
    // 帧率无关的阻尼：0.0015^(1/60) ⇒ 60fps 下每帧约收敛 10%
    const k = 1 - Math.pow(0.0015, dt);

    const target = page.mode === 'thinking' && !reduceMotion ? 1 : 0;
    blend += (target - blend) * k;
    appear += (1 - appear) * (1 - Math.pow(0.002, dt));

    // 思考：持续转圈（证明它是立体的）；待机：转速归零
    spin += THREE.MathUtils.lerp(0, 1.15, blend) * dt;
    if (blend < 0.995) {
      const nearest = Math.round(spin / TAU) * TAU;
      spin += (nearest - spin) * (1 - blend) * 0.06;
    }

    const speed = 0.55 + 0.55 * blend;
    model.rotation.y = Math.sin(t * speed) * THREE.MathUtils.lerp(0.45, 0.1, blend) + spin;
    model.rotation.z = Math.sin(t * (1.1 + 0.9 * blend)) * THREE.MathUtils.lerp(0.03, 0.08, blend);
    model.rotation.x = Math.sin(t * (2.0 + blend)) * 0.5 * THREE.MathUtils.lerp(0, 0.07, blend);
    model.position.y = Math.sin(t * (1.1 + 0.9 * blend)) * THREE.MathUtils.lerp(0.05, 0.075, blend);

    root.scale.setScalar(THREE.MathUtils.lerp(0.62, 1, appear));

    // 眨眼：三角波，3~6 秒一次
    blinkIn -= dt;
    if (blinkIn <= 0) {
      blinkLeft = 0.13;
      blinkIn = 2.6 + Math.random() * 3.4;
    }
    let closed = 0;
    if (blinkLeft > 0) {
      blinkLeft -= dt;
      closed = Math.max(0, 1 - Math.abs(blinkLeft - 0.065) / 0.065);
    }
    for (const eye of eyes) eye.scale.y = 1 - closed * 0.9;

    renderer.render(scene, camera);
  }
  animate();

  // 初始化成功才切换：在此之前页面显示二维图，失败也自然停留在二维图上。
  stage.hidden = false;
  fallbackImg.hidden = true;
}

try {
  init();
} catch (err) {
  console.warn('[mascot3d] 3D 初始化失败，回退二维图：', err);
}

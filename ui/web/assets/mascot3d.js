/**
 * 饮食助手互动小人「橘子人」—— 3D 形象。
 *
 * 为什么是程序化建模，而不是导入一个 .glb：
 *   1. 仓库只需多带一个 670KB 的 three.js（已内联、不走 CDN），不必再背模型文件与授权；
 *   2. 设定稿（docs/design/diet-assistant-mascot-sheet.png）给的是三视图 + 配色方案 +
 *      身体比例（圆滚滚、高≈宽），球身 + 灰风镜 + 胸前徽记这个结构用几何体就能精确还原；
 *   3. 「idle ↔ 思考中」两种状态要在**同一个场景里连续过渡** —— 换图片做不到衔接流畅，
 *      只会看到一帧跳变。这里所有动画量都由同一个阻尼系数驱动（见 animate()）。
 *
 * 降级策略：WebGL 不可用、three.js 加载失败或上下文丢失时，本模块保持不生效，
 *   页面继续显示二维的 assets/mascot.png（<img class="mascot-img">）。
 *   那个 <img> 同时也是 core/tests/test_web_assets.py 的依赖，不能删。
 *
 * 与页面的状态约定：经典脚本只写 window.TA_MASCOT.mode（状态名：idle / listening / thinking /
 *   searching / computing / waiting / caution / done / failed，已由页面按优先级仲裁好），
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

/**
 * 果皮纹理：一张 1024×512 的等距展开图（对应 SphereGeometry 的 UV，u 绕一圈、v 从顶到底）。
 * 同一套随机点同时画进 颜色 / 凹凸 / 粗糙度 三张图，保证「看到的斑点」和「光影里的凹坑」对得上。
 *   - 油胞凹点：真实橘皮最明显的纹理，密而小，靠 bump 在受光面产生细碎明暗；
 *   - 瓣纹：从果蒂向下的 10 条极浅凹槽，暗示里面一瓣一瓣，转身时会随光线若隐若现；
 *   - 果蒂周围一圈放射褶皱 + 颜色偏深，底部偏红橙，顶部略偏黄，避免像塑料球。
 * 两极处 u 方向被压缩，所以点的横向半径按 1/sin(纬度) 放大，避免极点附近糊成一团。
 */
function makePeelMaps() {
  const W = 1024, H = 512;
  const mk = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return [c, c.getContext('2d')]; };
  const [cc, col] = mk();   // 颜色
  const [bc, bmp] = mk();   // 凹凸（灰 128 为基准，越暗越凹）
  const [rc, rgh] = mk();   // 粗糙度（越亮越粗糙；凹坑里更粗糙，表面蜡质更光滑）

  // 底色：纵向渐变（顶偏黄、腰正橙、底偏红）
  const grad = col.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0.0, '#e9902a');
  grad.addColorStop(0.18, '#f7952a');
  grad.addColorStop(0.55, '#f5851f');
  grad.addColorStop(1.0, '#df5f12');
  col.fillStyle = grad; col.fillRect(0, 0, W, H);
  bmp.fillStyle = '#808080'; bmp.fillRect(0, 0, W, H);
  rgh.fillStyle = '#7a7a7a'; rgh.fillRect(0, 0, W, H);

  // 大块色斑：成熟度不均
  for (let i = 0; i < 160; i++) {
    const x = Math.random() * W, y = Math.random() * H, r = 18 + Math.random() * 46;
    const warm = Math.random() < 0.5;
    const g = col.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, warm ? 'rgba(214,82,10,0.20)' : 'rgba(255,178,70,0.16)');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    col.fillStyle = g; col.beginPath(); col.arc(x, y, r, 0, TAU); col.fill();
  }

  // 瓣纹：10 条从顶到底的浅槽（u 方向等分），两端收窄
  for (let k = 0; k < 10; k++) {
    const x0 = (k + 0.5) * W / 10;
    for (let y = 0; y < H; y += 2) {
      const lat = Math.sin(Math.PI * (y + 0.5) / H);       // 0（极点）→1（赤道）
      const w = 3 + 5 * lat;
      const g = bmp.createLinearGradient(x0 - w, 0, x0 + w, 0);
      g.addColorStop(0, 'rgba(128,128,128,0)');
      g.addColorStop(0.5, `rgba(96,96,96,${0.55 * lat})`);
      g.addColorStop(1, 'rgba(128,128,128,0)');
      bmp.fillStyle = g; bmp.fillRect(x0 - w, y, 2 * w, 2);
      col.fillStyle = `rgba(200,80,10,${0.06 * lat})`; col.fillRect(x0 - w * 0.5, y, w, 2);
    }
  }

  // 果蒂放射褶皱（v≈0 一带）
  for (let k = 0; k < 28; k++) {
    const x = (k / 28) * W + Math.random() * 10;
    const len = 30 + Math.random() * 40;
    bmp.strokeStyle = 'rgba(80,80,80,0.5)'; bmp.lineWidth = 2;
    bmp.beginPath(); bmp.moveTo(x, 0); bmp.lineTo(x + (Math.random() - 0.5) * 8, len); bmp.stroke();
  }
  const capG = col.createLinearGradient(0, 0, 0, 60);
  capG.addColorStop(0, 'rgba(150,90,20,0.55)'); capG.addColorStop(1, 'rgba(150,90,20,0)');
  col.fillStyle = capG; col.fillRect(0, 0, W, 60);

  // 油胞凹点：主纹理
  for (let i = 0; i < 9000; i++) {
    const x = Math.random() * W, y = Math.random() * H;
    const lat = Math.max(0.12, Math.sin(Math.PI * y / H));
    const r = 1.4 + Math.random() * 2.4;
    const rx = r / lat;
    // 凹凸：中心暗、外圈略亮（凹坑边缘鼓起）
    bmp.save(); bmp.translate(x, y); bmp.scale(rx / r, 1);
    const g = bmp.createRadialGradient(0, 0, 0, 0, 0, r * 1.5);
    g.addColorStop(0, 'rgba(55,55,55,0.9)');
    g.addColorStop(0.6, 'rgba(128,128,128,0.25)');
    g.addColorStop(0.85, 'rgba(165,165,165,0.35)');
    g.addColorStop(1, 'rgba(128,128,128,0)');
    bmp.fillStyle = g; bmp.beginPath(); bmp.arc(0, 0, r * 1.5, 0, TAU); bmp.fill();
    bmp.restore();
    // 颜色：凹处略深
    col.save(); col.translate(x, y); col.scale(rx / r, 1);
    col.fillStyle = 'rgba(200,85,12,0.22)'; col.beginPath(); col.arc(0, 0, r * 0.8, 0, TAU); col.fill();
    col.restore();
    // 粗糙度：凹处更哑
    rgh.save(); rgh.translate(x, y); rgh.scale(rx / r, 1);
    rgh.fillStyle = 'rgba(210,210,210,0.5)'; rgh.beginPath(); rgh.arc(0, 0, r, 0, TAU); rgh.fill();
    rgh.restore();
  }

  const tex = (c, srgb) => {
    const t = new THREE.CanvasTexture(c);
    if (srgb) t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = THREE.RepeatWrapping; t.wrapT = THREE.ClampToEdgeWrapping;
    t.anisotropy = 4;
    return t;
  };
  return { map: tex(cc, true), bumpMap: tex(bc, false), roughnessMap: tex(rc, false) };
}

/** 四肢用的小块凹点（重复贴），和身体同一种橘皮质感。 */
function makeLimbBump() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#808080'; ctx.fillRect(0, 0, size, size);
  for (let i = 0; i < 1100; i++) {
    const x = Math.random() * size, y = Math.random() * size, r = 1.3 + Math.random() * 2.2;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, 'rgba(60,60,60,0.85)'); g.addColorStop(1, 'rgba(128,128,128,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, TAU); ctx.fill();
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(2, 2);
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
  // 果皮用物理材质：clearcoat 模拟橘皮表面那层薄蜡光，高光会随转身在油胞间滑动；
  // sheen 给边缘一点柔和绒感，避免轮廓发硬。
  const peel = makePeelMaps();
  const peelMat = new THREE.MeshPhysicalMaterial({
    map: peel.map,
    bumpMap: peel.bumpMap,
    bumpScale: 1.6,
    roughnessMap: peel.roughnessMap,
    roughness: 0.55,
    metalness: 0.0,
    clearcoat: 0.45,
    clearcoatRoughness: 0.38,
    sheen: 0.35,
    sheenRoughness: 0.6,
    sheenColor: new THREE.Color(0xffc27a),
  });
  const limbMat = new THREE.MeshPhysicalMaterial({
    color: 0xf07d1c,
    bumpMap: makeLimbBump(),
    bumpScale: 1.0,
    roughness: 0.6,
    clearcoat: 0.3,
    clearcoatRoughness: 0.45,
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
  const glints = [];
  for (const side of [-1, 1]) {
    const eye = new THREE.Mesh(eyeGeo, inkMat);
    onSurface(eye, PHI_FRONT + side * 0.3, 1.44, 1.038);
    const glint = new THREE.Mesh(glintGeo, maskMat);
    onSurface(glint, PHI_FRONT + side * 0.3 - 0.07, 1.375, 1.05);
    model.add(eye, glint);
    eyes.push(eye);
    glints.push(glint);
  }

  // 出错表情「><」：每只眼两笔粗短墨线拼成尖角（左眼 >、右眼 <），贴在同一位置的风镜上。
  // 和圆眼共存、靠缩放交替，这样出错状态进出时是渐变，不会跳一帧。
  const strokeGeo = new THREE.BoxGeometry(0.17, 0.042, 0.012);
  const xEyes = [];
  for (const side of [-1, 1]) {
    const holder = new THREE.Group();
    const dir = -side; // 左眼(side=-1)尖角朝右成 >，右眼朝左成 <
    for (const up of [1, -1]) {
      const st = new THREE.Mesh(strokeGeo, inkMat);
      st.position.set(0, up * 0.042, 0);
      st.rotation.z = -up * dir * 0.5;
      holder.add(st);
    }
    onSurface(holder, PHI_FRONT + side * 0.3, 1.44, 1.04);
    holder.scale.setScalar(0.0001);
    model.add(holder);
    xEyes.push(holder);
  }

  // 微笑：半环，转 π 让开口朝上成 ∪。
  // 注意：onSurface 里的 lookAt 会覆盖网格自身的 rotation，所以翻转要放在内层，
  // 外层容器再贴到球面上；否则半环保持 ∩ 形，看起来是嘴角向下。
  const smile = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.021, 8, 40, Math.PI), inkMat);
  smile.rotation.z = Math.PI;
  const smileHolder = new THREE.Group();
  smileHolder.add(smile);
  onSurface(smileHolder, PHI_FRONT, 1.80, 1.03);
  model.add(smileHolder);

  // 出错嘴型：一条 5 段的小锯齿线（墨色），替代微笑
  const zig = new THREE.Group();
  const ZN = 5, ZW = 0.3, ZA = 0.03;
  const segLen = Math.hypot(ZW / ZN, 2 * ZA);
  const segGeo = new THREE.BoxGeometry(segLen + 0.02, 0.024, 0.012); // 略加长，接缝处不露缝
  for (let i = 0; i < ZN; i++) {
    const seg = new THREE.Mesh(segGeo, inkMat);
    const up = i % 2 === 0 ? 1 : -1;
    seg.position.set(-ZW / 2 + (i + 0.5) * ZW / ZN, 0, 0);
    seg.rotation.z = up * Math.atan2(2 * ZA, ZW / ZN);
    zig.add(seg);
  }
  const zigHolder = new THREE.Group();
  zigHolder.add(zig);
  onSurface(zigHolder, PHI_FRONT, 1.80, 1.032);
  zigHolder.scale.setScalar(0.0001);
  model.add(zigHolder);

  // 胸前茶叶徽记（替换原绿十字：本工具只做饮食参考，不用医疗符号）。
  // 叶片=压扁拉长的球，中脉=细长盒；lookAt 后局部 Z 为法线方向。
  // emissive 预留给「完成」状态：叶子亮一下表示答完了
  const badgeMat = new THREE.MeshStandardMaterial({ color: PALETTE.leaf, roughness: 0.45, emissive: 0x7dff9a, emissiveIntensity: 0 });
  const veinMat = new THREE.MeshStandardMaterial({ color: 0x9fd39a, roughness: 0.5 });
  const badge = new THREE.Group();
  const blade = new THREE.Mesh(new THREE.SphereGeometry(0.2, 28, 16), badgeMat);
  blade.scale.set(0.62, 1.0, 0.16);
  badge.add(blade);
  const vein = new THREE.Mesh(new THREE.BoxGeometry(0.018, 0.3, 0.02), veinMat);
  vein.position.z = 0.03;
  badge.add(vein);
  const petiole = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.016, 0.09, 8), badgeMat);
  petiole.position.y = -0.23;
  badge.add(petiole);
  badge.rotation.z = -0.5; // 斜放更像一片叶子
  const badgeHolder = new THREE.Group();
  badgeHolder.add(badge);
  onSurface(badgeHolder, PHI_FRONT, 2.32, 1.02);
  model.add(badgeHolder);

  // 四肢：设定稿是短粗的水滴形，用压扁拉长的球近似。
  // 手臂要做挥手、举牌、捧本子等动作 ⇒ 每条挂在「肩」上的枢轴组里，
  // 网格向下偏移，这样旋转枢轴就是绕肩摆臂，而不是绕手臂中心打转。
  const armGeo = new THREE.SphereGeometry(0.2, 24, 16);
  const arms = [];
  for (const side of [-1, 1]) {
    const pivot = new THREE.Group();
    pivot.position.set(side * 0.8, 0.12, 0.1);
    const arm = new THREE.Mesh(armGeo, limbMat);
    arm.scale.set(0.85, 1.35, 0.85);
    arm.position.set(0, -0.24, 0);
    pivot.add(arm);
    pivot.rotation.z = side * 0.5;
    pivot.userData.side = side;
    model.add(pivot);
    arms.push(pivot);
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
  return { model, eyes, glints, xEyes, zigHolder, arms, smile, badgeMat, leafMat, inkMat };
}

/**
 * 各状态的小道具，全部用基础几何体现搭（不引入新资源文件）。
 * 道具挂在 model 上，跟着身体一起转，光影也随之变化；平时 scale=0 藏起来，
 * 由状态权重渐入渐出，避免「啪」地出现。
 */
function buildProps(model, mats) {
  const props = {};

  // 查资料：一本摊开的小本子，两页各自能翻
  const paperMat = new THREE.MeshStandardMaterial({ color: 0xfffaf0, roughness: 0.7, side: THREE.DoubleSide });
  const coverMat = new THREE.MeshStandardMaterial({ color: 0x3a7d5a, roughness: 0.6 });
  const lineMat = new THREE.MeshBasicMaterial({ color: 0xb9b2a4 });
  const book = new THREE.Group();
  const cover = new THREE.Mesh(new THREE.BoxGeometry(0.64, 0.44, 0.03), coverMat);
  book.add(cover);
  const pages = [];
  for (const side of [-1, 1]) {
    const hinge = new THREE.Group(); // 书脊处的铰链：翻页绕它转
    hinge.position.z = 0.025;
    const page = new THREE.Mesh(new THREE.PlaneGeometry(0.29, 0.4), paperMat);
    page.position.x = side * 0.15;
    hinge.add(page);
    for (let i = 0; i < 4; i++) { // 几条横线，一看就是「本子」
      const ln = new THREE.Mesh(new THREE.PlaneGeometry(0.2, 0.012), lineMat);
      ln.position.set(side * 0.15, 0.12 - i * 0.075, 0.002);
      hinge.add(ln);
    }
    hinge.userData.side = side;
    book.add(hinge);
    pages.push(hinge);
  }
  book.position.set(0, -0.32, 1.05);
  book.rotation.x = -0.75; // 本子朝上斜，像低头在看
  model.add(book);
  props.book = book; props.pages = pages;

  // 查资料：头侧冒出的一片小茶叶图标
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.13, 18, 12), mats.leafMat);
  tip.scale.set(0.6, 1.0, 0.18);
  const tipHolder = new THREE.Group();
  tipHolder.add(tip);
  tipHolder.position.set(-0.72, 1.18, 0.3);
  tipHolder.rotation.z = 0.6;
  model.add(tipHolder);
  props.leafIcon = tipHolder;

  // 计算体质：绕身体转的一圈小算盘珠
  const beadMat = new THREE.MeshStandardMaterial({ color: 0x8a5a2b, roughness: 0.35 });
  const beads = new THREE.Group();
  const beadGeo = new THREE.SphereGeometry(0.075, 14, 10);
  for (let i = 0; i < 6; i++) {
    const b = new THREE.Mesh(beadGeo, beadMat);
    const a = i / 6 * TAU;
    b.position.set(Math.cos(a) * 1.18, 0, Math.sin(a) * 1.18);
    b.scale.set(1, 0.7, 1); // 算盘珠是扁的
    beads.add(b);
  }
  beads.position.y = -0.25;
  beads.rotation.x = 0.25;
  model.add(beads);
  props.beads = beads;

  // 安全提醒：右手举起的黄色提示牌，正面一个「!」
  const signMat = new THREE.MeshStandardMaterial({ color: 0xffc928, roughness: 0.5 });
  const stickMat = new THREE.MeshStandardMaterial({ color: 0x9b6b3d, roughness: 0.7 });
  const sign = new THREE.Group();
  const board = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.34, 0.04), signMat);
  sign.add(board);
  const bang = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.18, 0.02), mats.inkMat);
  bang.position.set(0, 0.04, 0.03);
  const dot = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.05, 0.02), mats.inkMat);
  dot.position.set(0, -0.11, 0.03);
  sign.add(bang, dot);
  const stick = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.42, 8), stickMat);
  stick.position.y = -0.38;
  sign.add(stick);
  sign.position.set(0.88, 1.1, 0.3);
  sign.rotation.z = -0.12;
  model.add(sign);
  props.sign = sign;

  // 出错：头侧一个小问号（半环 + 竖段 + 点）
  const qMat = new THREE.MeshStandardMaterial({ color: 0x4a6fa5, roughness: 0.4 });
  const q = new THREE.Group();
  const hook = new THREE.Mesh(new THREE.TorusGeometry(0.09, 0.028, 8, 24, Math.PI * 1.4), qMat);
  hook.rotation.z = -0.45 * Math.PI;
  hook.position.y = 0.08;
  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.028, 0.028, 0.08, 8), qMat);
  neck.position.y = -0.04;
  const qdot = new THREE.Mesh(new THREE.SphereGeometry(0.034, 10, 8), qMat);
  qdot.position.y = -0.15;
  q.add(hook, neck, qdot);
  q.position.set(-0.74, 1.12, 0.3); // 放左侧：右手在挠头，避免挡住
  model.add(q);
  props.question = q;

  for (const g of [book, tipHolder, beads, sign, q]) { g.scale.setScalar(0); g.visible = false; }
  return props;
}

/** 道具按权重缩放；权重近 0 时直接不渲染，省一点开销。 */
function showProp(obj, w, base = 1) {
  obj.visible = w > 0.01;
  obj.scale.setScalar(Math.max(0, w) * base);
}

// 每个状态下两条手臂（左、右）的目标姿态：[rotX, rotZ]，绕肩旋转。
// rotZ 对右臂为正 = 向外向上抬（π 附近就是举过头顶），左臂取负号对称。
// 各状态按权重加权平均 ⇒ 状态切换时手臂是滑过去的，不会瞬移。
const ARM_POSE = {
  idle:      [[0, -0.5], [0, 0.5]],
  listening: [[-0.2, -0.45], [-0.2, 0.45]],
  thinking:  [[0, -0.5], [-0.9, -0.3]],     // 右手抬到下巴附近，像托腮
  searching: [[-1.25, -0.25], [-1.25, 0.25]], // 双手向前捧本子
  computing: [[0, -0.75], [0, 0.75]],
  waiting:   [[0, -0.5], [0, 2.4]],         // 右手高举（挥手在 animate 里叠加摆动）
  caution:   [[0, -0.5], [-0.35, 2.6]],     // 右手举牌
  done:      [[0, -0.6], [0, 0.6]],
  failed:    [[0, -0.5], [-0.3, 2.85]],     // 右手绕到头侧挠头
};
// 身体姿态目标：[rotX(前倾+), rotY(转向), rotZ(歪头)]
const BODY_POSE = {
  idle:      [0, 0, 0],
  listening: [0.16, -0.38, 0.05],  // 前倾、侧身朝向左侧的聊天框
  thinking:  [-0.08, -0.25, 0.2],
  searching: [0.2, 0, 0],          // 低头看本子
  computing: [0, 0, 0],
  waiting:   [0, -0.35, -0.06],    // 面向聊天框
  caution:   [0, 0, 0],            // 正对用户，认真
  done:      [0, 0, 0],
  failed:    [0, 0.1, -0.16],
};
const STATE_NAMES = Object.keys(ARM_POSE);

/**
 * 一只小人的「场景 + 姿态驱动」。抽出来是为了能实例化多只（状态展柜页），
 * 应用内那只仍由 init() 用同一份逻辑驱动，行为不变。
 *   getMode：每帧取状态名；showcase：展柜模式——不原地转圈、少张望、
 *   点头/发光这类一次性动作改成循环播放，并带一点 3/4 侧身，方便看清道具。
 */
function createRig({ getMode, spinAfter, reduceMotion, showcase = false, aspect = 96 / 132 }) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, aspect, 0.1, 50);
  camera.position.set(0, 0.1, 6.2);
  camera.lookAt(0, 0.05, 0);

  // 灯光全部固定在世界坐标里、不挂在模型上：小人转身/转圈时，
  // 受光面、高光和背光轮廓会跟着变化，看起来才是「立体的东西在光里转」。
  scene.add(new THREE.HemisphereLight(0xfff3e0, 0xc9b79c, 0.7));
  const key = new THREE.DirectionalLight(0xfff4e6, 2.1);   // 主光：左上前方，暖白
  key.position.set(2.6, 4.2, 3.4);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xffd9a8, 0.45); // 补光：右侧，压暗部不死黑
  fill.position.set(-3.2, 1.2, 2.2);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0xfff0d0, 1.4);   // 轮廓光：后上方，勾出果皮边缘
  rim.position.set(-1.5, 2.5, -4);
  scene.add(rim);
  const bounce = new THREE.PointLight(0xffb066, 0.6, 6);   // 地面反光：下巴/肚子底部的暖色回光
  bounce.position.set(0, -2, 1.5);
  scene.add(bounce);

  const root = new THREE.Group();
  const { model, eyes, glints, xEyes, zigHolder, arms, smile, badgeMat, leafMat, inkMat } = buildCharacter();
  const props = buildProps(model, { leafMat, inkMat });
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
  // 每个状态一个权重，都朝 0/1 阻尼收敛：切换时旧状态渐出、新状态渐入，不会跳变
  const w = Object.fromEntries(STATE_NAMES.map(n => [n, n === 'idle' ? 1 : 0]));
  let blend = 0;    // 「思考」状态的权重，驱动原有的歪头/转圈动作
  let thinkT = 0;   // 本次思考已持续的秒数
  let stateT = 0;   // 当前状态已持续的秒数（点头、挥手等一次性动作用）
  let lastMode = 'idle';
  // 可调：思考多久开始转圈、多久转到全速、全速角速度（弧度/秒）。
  // 允许页面用 window.TA_MASCOT.spinAfter 覆盖，方便以后按任务类型调。
  const SPIN_AFTER = Number(spinAfter) || 4;
  const SPIN_RAMP = 1.5;
  const SPIN_SPEED = 2.4;
  let spin = 0;     // 累计转角；不转时被拉回最近整圈，确保停在正脸
  let appear = 0;   // 入场 0→1
  let t = 0;
  let blinkIn = 2.5;
  let blinkLeft = 0;
  function step(dt) {
      t += dt;
      // 帧率无关的阻尼：0.0015^(1/60) ⇒ 60fps 下每帧约收敛 10%
      const k = 1 - Math.pow(0.0015, dt);

      const want = getMode();
    const mode = ARM_POSE[want] ? want : 'idle';
      stateT = mode === lastMode ? stateT + dt : 0;
      lastMode = mode;
      for (const n of STATE_NAMES) w[n] += ((n === mode ? 1 : 0) - w[n]) * k;
      // 减少动态效果：只保留静态姿态和道具，去掉所有周期摆动与转圈
      const m = reduceMotion ? 0 : 1;
      blend = w.thinking;
      appear += (1 - appear) * (1 - Math.pow(0.002, dt));

      // 思考计时：只有「思考」本身会累计到转圈；查资料/计算有自己的动作，不转圈
      thinkT = mode === 'thinking' ? thinkT + dt : 0;
      // 思考越久动作越大：前 SPIN_AFTER 秒只歪头琢磨；超过后在 SPIN_RAMP 秒内渐入原地转圈，
      // 让用户知道「还在忙、没卡住」。转速同样受 blend 控制，不会突然起转。
      const spinIn = (reduceMotion || showcase) ? 0
        : THREE.MathUtils.smoothstep(thinkT, SPIN_AFTER, SPIN_AFTER + SPIN_RAMP);
      spin += SPIN_SPEED * spinIn * blend * dt;
      // 不转的时候（含回待机）把累计角拉回最近整圈，保证最后停在正脸
      if (spinIn < 0.01) {
        const nearest = Math.round(spin / TAU) * TAU;
        spin += (nearest - spin) * (1 - Math.pow(0.02, dt));
      }

      // 身体基础姿态 = 各状态目标按权重加权
      let bx = 0, by = 0, bz = 0;
      for (const n of STATE_NAMES) {
        bx += BODY_POSE[n][0] * w[n]; by += BODY_POSE[n][1] * w[n]; bz += BODY_POSE[n][2] * w[n];
      }
      const idleSway = (w.idle + w.listening * 0.3 + w.done * 0.5) * (showcase ? 0.25 : 1); // 待机时左右张望，其他状态收敛
      // 完成：点头两下（衰减正弦）；出错：歪头小幅来回，像在挠头琢磨
      // 展柜里一次性动作循环播放（每 2.4 秒一轮），否则截图时早就停了
    const oneT = showcase ? stateT % 2.4 : stateT;
    const nod = w.done * Math.sin(Math.min(oneT, 1.2) * TAU * 1.6) * 0.22 * Math.max(0, 1 - oneT / 1.2) * m;
      const tilt = bz * (1 - 0.6 * spinIn) + Math.sin(t * 3) * 0.04 * w.failed * m;
      model.rotation.y = spin
        + Math.sin(t * 0.55) * 0.45 * idleSway * (1 - spinIn) * m
        + Math.sin(t * 0.55) * 0.12 * blend * (1 - spinIn) * m
        + by * (1 - spinIn)
      + (showcase ? 0.28 : 0); // 展柜：略侧身成 3/4，立体感和道具都更清楚
      model.rotation.z = tilt + Math.sin(t * 1.1) * 0.03 * m;
      model.rotation.x = bx * (1 - spinIn) + nod + Math.sin(t * 2.2) * 0.03 * blend * m;
      // 计算体质：原地小跳（|sin| 形成落地-弹起的节奏）
      const hop = Math.abs(Math.sin(t * 5.5)) * 0.18 * w.computing * m;
      model.position.y = Math.sin(t * (1.1 + 0.6 * blend + 1.2 * spinIn)) * 0.05 * m + hop;

      // 手臂：姿态加权 + 各状态的摆动
      arms.forEach((pivot, idx) => {
        let rx = 0, rz = 0;
        for (const n of STATE_NAMES) { rx += ARM_POSE[n][idx][0] * w[n]; rz += ARM_POSE[n][idx][1] * w[n]; }
        if (idx === 1) {
          rz += Math.sin(t * 7) * 0.35 * w.waiting * m;   // 挥手
          rx += Math.sin(t * 9) * 0.18 * w.failed * m;    // 挠头
        }
        rx += Math.sin(t * 4) * 0.05 * w.searching * m;   // 捧本子时轻轻抖
        pivot.rotation.x = rx;
        pivot.rotation.z = rz;
      });

      // 嘴：平时微笑；安全提醒时压扁成一条横线，表情认真
      smile.scale.y = THREE.MathUtils.lerp(1, 0.12, w.caution);
      // 出错：圆眼/微笑缩没，「><」眼和锯齿嘴缩出来（权重驱动，渐变切换）
      const fOn = Math.max(0.0001, w.failed), fOff = Math.max(0.0001, 1 - w.failed);
      smile.scale.x = fOff; smile.scale.y *= fOff;
      for (const g of glints) g.scale.setScalar(fOff);
      for (const x of xEyes) x.scale.setScalar(fOn);
      zigHolder.scale.setScalar(fOn);
      // 完成：胸口茶叶亮一下
      badgeMat.emissiveIntensity = w.done * 0.9 * Math.max(0, 1 - (showcase ? oneT : stateT) / 1.6);

      // 道具
      showProp(props.book, w.searching);
      props.pages.forEach(h => {
        const flip = (Math.sin(t * 3 + (h.userData.side > 0 ? 0 : Math.PI)) * 0.5 + 0.5) * m;
        h.rotation.y = -h.userData.side * (0.35 + 0.6 * flip * (h.userData.side > 0 ? 1 : 0.2));
      });
      showProp(props.leafIcon, w.searching);
      props.leafIcon.position.y = 1.18 + Math.sin(t * 3) * 0.05 * m;
      showProp(props.beads, w.computing);
      props.beads.rotation.y = t * 2.2 * m;
      showProp(props.sign, w.caution);
      props.sign.rotation.z = -0.12 + Math.sin(t * 2) * 0.04 * m;
      showProp(props.question, w.failed);
      props.question.position.y = 1.12 + Math.sin(t * 2.5) * 0.04 * m;

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
      // 思考时保持睁眼微笑，只保留正常眨眼
      // 「><」显示时不眨眼（眨眼量随出错权重压到 0）
      closed *= 1 - w.failed;
      for (const eye of eyes) eye.scale.set(fOff, (1 - closed * 0.9) * fOff, 1);
  }

  return { scene, camera, step };
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
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const reduceMotion = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let running = true;
  const page = window.TA_MASCOT || (window.TA_MASCOT = { mode: 'idle' });

  const { scene, camera, step } = createRig({
    getMode: () => page.mode,
    spinAfter: (window.TA_MASCOT || {}).spinAfter,
    reduceMotion,
  });


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
    step(dt);
    renderer.render(scene, camera);
  }
  animate();

  // 初始化成功才切换：在此之前页面显示二维图，失败也自然停留在二维图上。
  stage.hidden = false;
  fallbackImg.hidden = true;
}

/**
 * 状态展柜：一个 WebGL 渲染器 + 剪裁视口，同时画多只小人。
 * 为什么不每格一个 canvas：浏览器对同页 WebGL 上下文数有上限（常见 8~16），
 * 9 格各开一个容易触发「最老的上下文被回收」，格子随机变空白。
 *   canvas：铺满页面的透明画布；cells：[{ el, state }]，el 决定这一格的位置大小。
 */
export function createGallery(canvas, cells) {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.setScissorTest(true);
  const reduceMotion = window.matchMedia
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rigs = cells.map(c => ({ el: c.el, ...createRig({
    getMode: () => c.state, reduceMotion, showcase: true, aspect: 260 / 340,
  }) }));
  const clock = new THREE.Clock();
  function frame() {
    requestAnimationFrame(frame);
    const dt = Math.min(clock.getDelta(), 0.05);
    const W = canvas.clientWidth, H = canvas.clientHeight;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(W, H, false);
    renderer.setScissor(0, 0, W, H); renderer.setViewport(0, 0, W, H); renderer.clear();
    const box = canvas.getBoundingClientRect();
    for (const r of rigs) {
      r.step(dt);
      const b = r.el.getBoundingClientRect();
      if (b.bottom < box.top || b.top > box.bottom) continue; // 滚出屏幕的格子不画
      const x = b.left - box.left, y = box.bottom - b.bottom; // WebGL 视口原点在左下
      renderer.setViewport(x, y, b.width, b.height);
      renderer.setScissor(x, y, b.width, b.height);
      r.camera.aspect = b.width / b.height; r.camera.updateProjectionMatrix();
      renderer.render(r.scene, r.camera);
    }
  }
  frame();
  return renderer;
}

try {
  init();
} catch (err) {
  console.warn('[mascot3d] 3D 初始化失败，回退二维图：', err);
}

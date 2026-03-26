import * as THREE from "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js";
import { OrbitControls } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/STLLoader.js";

let scene = null;
let camera = null;
let renderer = null;
let controls = null;
let mesh = null;

function setPreviewStatus(message) {
  const el = document.getElementById("preview-status");
  if (el) {
    el.textContent = message;
  }
  console.log("[preview]", message);
}

function clearMesh() {
  if (!mesh || !scene) return;

  scene.remove(mesh);

  if (mesh.geometry) {
    mesh.geometry.dispose();
  }
  if (mesh.material) {
    mesh.material.dispose();
  }

  mesh = null;
}

function fitCameraToGeometry(geometry) {
  geometry.computeBoundingBox();

  const box = geometry.boundingBox;
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();

  box.getSize(size);
  box.getCenter(center);

  const maxDim = Math.max(size.x, size.y, size.z) || 50;
  const fov = camera.fov * (Math.PI / 180);
  let distance = maxDim / (2 * Math.tan(fov / 2));
  distance *= 1.8;

  camera.position.set(distance, -distance, distance * 0.8);
  camera.near = Math.max(0.1, distance / 100);
  camera.far = distance * 20;
  camera.updateProjectionMatrix();

  controls.target.set(0, 0, 0);
  controls.update();

  return center;
}

function initPreview() {
  const canvas = document.getElementById("preview-canvas");
  if (!canvas) {
    console.error("[preview] canvas not found");
    return;
  }

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf3f8fd);

  const width = canvas.clientWidth || 900;
  const height = canvas.clientHeight || 560;

  camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 2000);
  camera.position.set(150, -150, 120);

  renderer = new THREE.WebGLRenderer({
    canvas: canvas,
    antialias: true,
    alpha: false
  });
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  renderer.setSize(width, height, false);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.screenSpacePanning = true;

  const ambient = new THREE.AmbientLight(0xffffff, 0.8);
  scene.add(ambient);

  const dir1 = new THREE.DirectionalLight(0xffffff, 1.0);
  dir1.position.set(120, 150, 180);
  scene.add(dir1);

  const dir2 = new THREE.DirectionalLight(0xffffff, 0.45);
  dir2.position.set(-80, -100, 120);
  scene.add(dir2);

  const grid = new THREE.GridHelper(300, 20, 0xcfd8e3, 0xe5edf5);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = -8;
  scene.add(grid);

  function animate() {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  }

  function handleResize() {
    const w = canvas.clientWidth || 900;
    const h = canvas.clientHeight || 560;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }

  window.addEventListener("resize", handleResize);
  handleResize();

  setPreviewStatus("Preview initialized.");
  animate();
}

async function loadPreview(url) {
  if (!scene) {
    initPreview();
  }

  if (!url) {
    setPreviewStatus("No STL URL provided.");
    return;
  }

  const absoluteUrl = new URL(url, window.location.origin).toString();
  const requestUrl = absoluteUrl + (absoluteUrl.includes("?") ? "&" : "?") + "t=" + Date.now();

  setPreviewStatus("Fetching STL: " + absoluteUrl);

  try {
    const response = await fetch(requestUrl, { cache: "no-store" });

    if (!response.ok) {
      throw new Error("HTTP " + response.status + " while fetching STL");
    }

    const buffer = await response.arrayBuffer();

    if (!buffer || buffer.byteLength === 0) {
      throw new Error("Empty STL file");
    }

    const loader = new STLLoader();
    const geometry = loader.parse(buffer);

    geometry.computeVertexNormals();

    clearMesh();

    const material = new THREE.MeshStandardMaterial({
      color: 0x4aa3ff,
      metalness: 0.08,
      roughness: 0.78
    });

    mesh = new THREE.Mesh(geometry, material);

    const center = fitCameraToGeometry(geometry);
    mesh.position.set(-center.x, -center.y, -center.z);

    scene.add(mesh);

    setPreviewStatus("Preview loaded successfully.");
  } catch (err) {
    console.error("[preview] load failed", err);
    setPreviewStatus("Preview error: " + (err.message || String(err)));
  }
}

window.updatePreview = function (url) {
  console.log("[preview] updatePreview called with:", url);
  loadPreview(url);
};

window.addEventListener("load", function () {
  initPreview();
});

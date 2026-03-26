import * as THREE from 
"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"; 
import { OrbitControls } from 
"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js"; 
import { STLLoader } from 
"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/STLLoader.js"; 
let scene = null; let camera = null; let renderer = 
null; let controls = null; let mesh = null; function 
setPreviewStatus(message) {
    const el = 
    document.getElementById("preview-status"); if (el) 
    el.textContent = message;
}
function sleep(ms) { return new Promise(resolve => 
    setTimeout(resolve, ms));
}
function toAbsoluteUrl(url) { return new URL(url, 
    window.location.origin).toString();
}
function fitCameraToMesh(geometry) { 
    geometry.computeBoundingBox(); const box = 
    geometry.boundingBox; const size = new 
    THREE.Vector3(); box.getSize(size); const center = 
    new THREE.Vector3(); box.getCenter(center); const 
    maxDim = Math.max(size.x, size.y, size.z) || 50; 
    const fov = camera.fov * (Math.PI / 180); let 
    distance = maxDim / (2 * Math.tan(fov / 2)); 
    distance *= 1.8; camera.position.set(distance, 
    -distance, distance * 0.8); camera.near = 
    Math.max(0.1, distance / 100); camera.far = 
    distance * 20; camera.updateProjectionMatrix(); 
    controls.target.set(0, 0, 0); controls.update(); 
    return center;
}
function clearCurrentMesh() { if (!mesh) return; 
    scene.remove(mesh); if (mesh.geometry) 
    mesh.geometry.dispose(); if (mesh.material) 
    mesh.material.dispose(); mesh = null;
}
function initPreview() { const canvas = 
    document.getElementById("preview-canvas"); scene = 
    new THREE.Scene(); scene.background = new 
    THREE.Color(0xf3f8fd); const width = 
    canvas.clientWidth || 900; const height = 
    canvas.clientHeight || 520; camera = new 
    THREE.PerspectiveCamera(45, width / height, 0.1, 
    2000); camera.position.set(150, -150, 120); 
    renderer = new THREE.WebGLRenderer({
        canvas, antialias: true, alpha: false
    });
    renderer.setPixelRatio(window.devicePixelRatio || 
    1); renderer.setSize(width, height, false); 
    controls = new OrbitControls(camera, 
    renderer.domElement); controls.enableDamping = 
    true; controls.dampingFactor = 0.08; 
    controls.screenSpacePanning = true; const ambient = 
    new THREE.AmbientLight(0xffffff, 0.8); 
    scene.add(ambient); const dir1 = new 
    THREE.DirectionalLight(0xffffff, 1.0); 
    dir1.position.set(120, 150, 180); scene.add(dir1); 
    const dir2 = new THREE.DirectionalLight(0xffffff, 
    0.45); dir2.position.set(-80, -100, 120); 
    scene.add(dir2); const grid = new 
    THREE.GridHelper(300, 20, 0xcfd8e3, 0xe5edf5); 
    grid.rotation.x = Math.PI / 2; grid.position.z = 
    -8; scene.add(grid); function animate() {
        requestAnimationFrame(animate); 
        controls.update(); renderer.render(scene, 
        camera);
    }
    function handleResize() { const w = 
        canvas.clientWidth || 900; const h = 
        canvas.clientHeight || 520; camera.aspect = w / 
        h; camera.updateProjectionMatrix(); 
        renderer.setSize(w, h, false);
    }
    window.addEventListener("resize", handleResize); 
    handleResize(); setPreviewStatus("No preview 
    yet."); animate();
}
async function fetchArrayBufferWithRetry(url, retries = 
6, delayMs = 700) {
    const absUrl = toAbsoluteUrl(url); for (let attempt 
    = 1; attempt <= retries; attempt++) {
        const cacheBustedUrl = 
        `${absUrl}${absUrl.includes("?") ? "&" : 
        "?"}t=${Date.now()}`; setPreviewStatus(`Loading 
        preview... attempt ${attempt}/${retries}`); try 
        {
            console.log("Fetching STL:", 
            cacheBustedUrl); const response = await 
            fetch(cacheBustedUrl, {
                method: "GET", cache: "no-store"
            });
            if (!response.ok) { const text = await 
                response.text(); console.warn("Preview 
                fetch failed:", response.status, 
                text.slice(0, 300)); if (attempt < 
                retries) {
                    await sleep(delayMs); continue;
                }
                throw new Error(`HTTP 
                ${response.status}`);
            }
            const buffer = await 
            response.arrayBuffer(); if (!buffer || 
            buffer.byteLength === 0) {
                if (attempt < retries) { await 
                    sleep(delayMs); continue;
                }
                throw new Error("empty STL file");
            }
            console.log("Preview bytes:", 
            buffer.byteLength); return buffer;
        } catch (error) {
            console.warn("Preview fetch error:", 
            error); if (attempt < retries) {
                await sleep(delayMs); continue;
            }
            throw error;
        }
    }
    throw new Error("preview fetch failed after 
    retries");
}
async function loadSTL(url) { const loader = new 
    STLLoader(); try {
        const buffer = await 
        fetchArrayBufferWithRetry(url, 6, 700); 
        clearCurrentMesh(); const geometry = 
        loader.parse(buffer); 
        geometry.computeVertexNormals(); const material 
        = new THREE.MeshStandardMaterial({
            color: 0x4aa3ff, metalness: 0.08, 
            roughness: 0.78
        });
        mesh = new THREE.Mesh(geometry, material); 
        const center = fitCameraToMesh(geometry); 
        mesh.position.set(-center.x, -center.y, 
        -center.z); scene.add(mesh); 
        setPreviewStatus("Preview loaded.");
    } catch (error) {
        console.error("STL preview error:", error); 
        setPreviewStatus(`Preview error: 
        ${error.message || error}`);
    }
}
window.updatePreview = function (fileUrl) { if (!scene) 
    {
        initPreview();
    }
    loadSTL(fileUrl);
};
window.addEventListener("load", () => { initPreview();
});

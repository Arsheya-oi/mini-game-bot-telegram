/* pet-bg.js – گربه پیکسلی low-poly در گوشه صفحه */
(function () {
  if (typeof THREE === 'undefined') {
    const script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
    script.onload = () => initScene();
    document.head.appendChild(script);
  } else {
    initScene();
  }

  function initScene() {
    const container = document.getElementById('three-container');
    if (!container) return;

    // --- صحنه با پس‌زمینه شفاف ---
    const scene = new THREE.Scene();
    scene.background = null; // شفاف

    // دوربین با زاویه مناسب برای دیدن گربه کوچک
    const camera = new THREE.PerspectiveCamera(30, container.clientWidth / container.clientHeight, 0.1, 100);
    camera.position.set(1.5, 1, 3);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.appendChild(renderer.domElement);

    // نور
    const ambient = new THREE.AmbientLight(0x404060);
    scene.add(ambient);

    const dirLight = new THREE.DirectionalLight(0xffeedd, 1);
    dirLight.position.set(1, 3, 2);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 256;
    dirLight.shadow.mapSize.height = 256;
    const d = 2;
    dirLight.shadow.camera.left = -d;
    dirLight.shadow.camera.right = d;
    dirLight.shadow.camera.top = d;
    dirLight.shadow.camera.bottom = -d;
    dirLight.shadow.camera.near = 0.5;
    dirLight.shadow.camera.far = 6;
    scene.add(dirLight);

    const backLight = new THREE.DirectionalLight(0x4488ff, 0.2);
    backLight.position.set(-1, 0.5, -2);
    scene.add(backLight);

    // صفحه زمین برای سایه (کوچک)
    const planeGeo = new THREE.PlaneGeometry(2, 2);
    const planeMat = new THREE.ShadowMaterial({ opacity: 0.2, color: 0x000000 });
    const plane = new THREE.Mesh(planeGeo, planeMat);
    plane.rotation.x = -Math.PI / 2;
    plane.position.y = -0.35;
    plane.receiveShadow = true;
    scene.add(plane);

    // ===== گربه پیکسلی =====
    const cat = new THREE.Group();
    cat.position.set(0, -0.1, 0);

    // بدنه
    const bodyGeo = new THREE.BoxGeometry(0.5, 0.3, 0.6);
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0xff9944, roughness: 0.6, flatShading: true });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    body.position.y = 0.15;
    body.castShadow = true;
    body.receiveShadow = true;
    cat.add(body);

    // سر
    const headGeo = new THREE.BoxGeometry(0.3, 0.25, 0.25);
    const headMat = new THREE.MeshStandardMaterial({ color: 0xff9944, roughness: 0.6, flatShading: true });
    const head = new THREE.Mesh(headGeo, headMat);
    head.position.set(0, 0.35, 0.25);
    head.castShadow = true;
    cat.add(head);

    // گوش‌ها (هرم ۴ وجهی)
    const earMat = new THREE.MeshStandardMaterial({ color: 0xff8844, flatShading: true });
    const earGeo = new THREE.ConeGeometry(0.08, 0.15, 4);
    const earL = new THREE.Mesh(earGeo, earMat);
    earL.position.set(-0.13, 0.45, 0.25);
    earL.rotation.z = -0.2;
    earL.rotation.x = -0.1;
    cat.add(earL);
    const earR = new THREE.Mesh(earGeo, earMat);
    earR.position.set(0.13, 0.45, 0.25);
    earR.rotation.z = 0.2;
    earR.rotation.x = -0.1;
    cat.add(earR);

    // چشم‌ها (دایره‌های ۶ ضلعی)
    const eyeMat = new THREE.MeshStandardMaterial({ color: 0x222222, flatShading: true });
    const eyeGeo = new THREE.CircleGeometry(0.04, 6);
    const eyeL = new THREE.Mesh(eyeGeo, eyeMat);
    eyeL.position.set(-0.08, 0.36, 0.35);
    cat.add(eyeL);
    const eyeR = new THREE.Mesh(eyeGeo, eyeMat);
    eyeR.position.set(0.08, 0.36, 0.35);
    cat.add(eyeR);

    // پلک‌ها برای خواب
    const lidMat = new THREE.MeshStandardMaterial({ color: 0xff9944, flatShading: true });
    const lidGeo = new THREE.CircleGeometry(0.045, 6, 0, Math.PI);
    const lidL = new THREE.Mesh(lidGeo, lidMat);
    lidL.position.set(-0.08, 0.37, 0.37);
    lidL.rotation.x = 0.1;
    cat.add(lidL);
    const lidR = new THREE.Mesh(lidGeo, lidMat);
    lidR.position.set(0.08, 0.37, 0.37);
    lidR.rotation.x = 0.1;
    cat.add(lidR);

    // بینی (مثلث)
    const noseMat = new THREE.MeshStandardMaterial({ color: 0xff8888, flatShading: true });
    const noseGeo = new THREE.ConeGeometry(0.025, 0.025, 3);
    const nose = new THREE.Mesh(noseGeo, noseMat);
    nose.position.set(0, 0.32, 0.38);
    nose.rotation.x = 0.2;
    cat.add(nose);

    // دم (چند مکعب)
    const tailMat = new THREE.MeshStandardMaterial({ color: 0xff8844, flatShading: true });
    const tailPos = [
      { pos: [0, 0.05, -0.4], s: [0.04, 0.04, 0.12] },
      { pos: [0.06, 0.1, -0.48], s: [0.04, 0.04, 0.12] },
      { pos: [0.12, 0.15, -0.42], s: [0.04, 0.04, 0.1] }
    ];
    tailPos.forEach(t => {
      const geo = new THREE.BoxGeometry(...t.s);
      const mesh = new THREE.Mesh(geo, tailMat);
      mesh.position.set(t.pos[0], t.pos[1], t.pos[2]);
      mesh.castShadow = true;
      cat.add(mesh);
    });

    // پاها
    const legMat = new THREE.MeshStandardMaterial({ color: 0xff8844, flatShading: true });
    const legPos = [[-0.2, -0.05, 0.2], [0.2, -0.05, 0.2], [-0.2, -0.05, -0.2], [0.2, -0.05, -0.2]];
    legPos.forEach(p => {
      const geo = new THREE.BoxGeometry(0.06, 0.12, 0.06);
      const leg = new THREE.Mesh(geo, legMat);
      leg.position.set(p[0], p[1], p[2]);
      leg.castShadow = true;
      cat.add(leg);
    });

    scene.add(cat);

    // ===== رخت‌خواب =====
    const bed = new THREE.Group();
    bed.position.set(-0.6, -0.25, 0.3);

    const mattressMat = new THREE.MeshStandardMaterial({ color: 0x4477aa, roughness: 0.8, flatShading: true });
    const mattressGeo = new THREE.CylinderGeometry(0.35, 0.35, 0.06, 6);
    const mattress = new THREE.Mesh(mattressGeo, mattressMat);
    mattress.position.y = 0.03;
    mattress.receiveShadow = true;
    mattress.castShadow = true;
    bed.add(mattress);

    const pillowMat = new THREE.MeshStandardMaterial({ color: 0x88aadd, roughness: 0.7, flatShading: true });
    const pillowGeo = new THREE.BoxGeometry(0.18, 0.06, 0.14);
    const pillow = new THREE.Mesh(pillowGeo, pillowMat);
    pillow.position.set(0, 0.08, -0.15);
    pillow.castShadow = true;
    bed.add(pillow);

    scene.add(bed);

    // ===== کاسه غذا =====
    const bowl = new THREE.Group();
    bowl.position.set(0.9, -0.25, 0.3);

    const bowlMat = new THREE.MeshStandardMaterial({ color: 0xcc8844, roughness: 0.6, metalness: 0.2, flatShading: true });
    const bowlGeo = new THREE.CylinderGeometry(0.25, 0.18, 0.08, 6);
    const bowlMesh = new THREE.Mesh(bowlGeo, bowlMat);
    bowlMesh.position.y = 0.04;
    bowlMesh.receiveShadow = true;
    bowlMesh.castShadow = true;
    bowl.add(bowlMesh);

    const foodMat = new THREE.MeshStandardMaterial({ color: 0xddaa44, roughness: 0.9, flatShading: true });
    for (let i = 0; i < 5; i++) {
      const foodGeo = new THREE.BoxGeometry(0.03 + Math.random()*0.02, 0.03, 0.03 + Math.random()*0.02);
      const food = new THREE.Mesh(foodGeo, foodMat);
      const angle = Math.random() * Math.PI * 2;
      const rad = Math.random() * 0.12;
      food.position.set(Math.cos(angle)*rad, 0.08, Math.sin(angle)*rad);
      food.castShadow = true;
      bowl.add(food);
    }
    scene.add(bowl);

    // ===== رفتار =====
    let isSleeping = true;
    let isAwake = false;
    let wakeTime = 0;
    let scrollTargetY = 0;

    const eyelids = [lidL, lidR];
    const eyes = [eyeL, eyeR];

    function goToSleep() {
      isSleeping = true;
      isAwake = false;
      eyelids.forEach(l => l.visible = true);
      eyes.forEach(e => e.visible = false);
      body.scale.set(1, 0.9, 1);
      head.scale.set(1, 0.9, 1);
    }

    function wakeUp() {
      if (isSleeping) {
        isSleeping = false;
        isAwake = true;
        wakeTime = Date.now();
        eyelids.forEach(l => l.visible = false);
        eyes.forEach(e => e.visible = true);
        body.scale.set(1, 1, 1);
        head.scale.set(1, 1, 1);
        // پرش
        cat.position.y += 0.08;
        setTimeout(() => { cat.position.y -= 0.08; }, 200);
        body.material.color.setHex(0xffaa66);
        head.material.color.setHex(0xffaa66);
        setTimeout(() => {
          body.material.color.setHex(0xff9944);
          head.material.color.setHex(0xff9944);
        }, 400);
      }
    }

    goToSleep();

    // کلیک روی گربه
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    renderer.domElement.addEventListener('click', (e) => {
      const rect = renderer.domElement.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObject(cat, true);
      if (intersects.length > 0) {
        wakeUp();
        if (!isSleeping && isAwake) {
          cat.position.y += 0.06;
          setTimeout(() => { cat.position.y -= 0.06; }, 150);
        }
      }
    });

    // اسکرول
    let lastScrollY = window.scrollY;
    window.addEventListener('scroll', () => {
      const currentScroll = window.scrollY;
      if (currentScroll !== lastScrollY) {
        if (isSleeping) wakeUp();
        const docEl = document.documentElement;
        const maxScroll = docEl.scrollHeight - window.innerHeight;
        const percent = maxScroll > 0 ? currentScroll / maxScroll : 0;
        scrollTargetY = -0.2 + percent * 0.8;
        lastScrollY = currentScroll;
      }
    });

    // انیمیشن
    function animate() {
      requestAnimationFrame(animate);

      cat.position.y += (scrollTargetY - cat.position.y) * 0.05;

      if (isAwake && !isSleeping && Date.now() - wakeTime > 6000) {
        goToSleep();
      }

      if (isSleeping) {
        const breath = Math.sin(Date.now() * 0.002) * 0.015;
        body.position.y = 0.15 + breath;
        head.position.y = 0.35 + breath * 0.5;
      }

      if (!isSleeping) {
        cat.rotation.z = Math.sin(Date.now() * 0.003) * 0.01;
      } else {
        cat.rotation.z = 0;
      }

      renderer.render(scene, camera);
    }
    animate();

    // تغییر اندازه
    window.addEventListener('resize', () => {
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });

    console.log('🐱 سیدی پیکسلی در گوشه صفحه');
  }
})();
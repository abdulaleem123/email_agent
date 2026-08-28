import React, { useEffect, useRef } from 'react'
import * as THREE from 'three'

/**
 * Lightweight three.js backdrop: a slowly rotating field of glowing points
 * with connecting lines — enterprise, calm, white/blue on navy. No gradients.
 * Cleans up fully on unmount; respects reduced-motion.
 */
export default function ThreeBackdrop() {
  const ref = useRef(null)

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const mount = ref.current
    if (!mount) return

    let w = mount.clientWidth, h = mount.clientHeight
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 100)
    camera.position.z = 26

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setSize(w, h)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    mount.appendChild(renderer.domElement)

    // points
    const COUNT = 90
    const positions = new Float32Array(COUNT * 3)
    const velocities = []
    for (let i = 0; i < COUNT; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 42
      positions[i * 3 + 1] = (Math.random() - 0.5) * 26
      positions[i * 3 + 2] = (Math.random() - 0.5) * 20
      velocities.push([(Math.random() - 0.5) * 0.01, (Math.random() - 0.5) * 0.01, (Math.random() - 0.5) * 0.01])
    }
    const pGeo = new THREE.BufferGeometry()
    pGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    const pMat = new THREE.PointsMaterial({ color: 0x8fb6ff, size: 0.4, transparent: true, opacity: 0.9 })
    const points = new THREE.Points(pGeo, pMat)
    scene.add(points)

    // connecting lines
    const lineMat = new THREE.LineBasicMaterial({ color: 0x2f7bf6, transparent: true, opacity: 0.16 })
    const lineGeo = new THREE.BufferGeometry()
    const lineSeg = new THREE.LineSegments(lineGeo, lineMat)
    scene.add(lineSeg)

    const group = new THREE.Group()
    group.add(points); group.add(lineSeg)
    scene.add(group)

    let raf
    const linkDist = 6
    const rebuildLines = () => {
      const pts = []
      for (let i = 0; i < COUNT; i++) {
        for (let j = i + 1; j < COUNT; j++) {
          const dx = positions[i * 3] - positions[j * 3]
          const dy = positions[i * 3 + 1] - positions[j * 3 + 1]
          const dz = positions[i * 3 + 2] - positions[j * 3 + 2]
          if (dx * dx + dy * dy + dz * dz < linkDist * linkDist) {
            pts.push(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2],
                     positions[j * 3], positions[j * 3 + 1], positions[j * 3 + 2])
          }
        }
      }
      lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
      lineGeo.attributes.position.needsUpdate = true
    }

    const tick = () => {
      for (let i = 0; i < COUNT; i++) {
        for (let a = 0; a < 3; a++) {
          positions[i * 3 + a] += velocities[i][a]
          const lim = a === 0 ? 21 : a === 1 ? 13 : 10
          if (positions[i * 3 + a] > lim || positions[i * 3 + a] < -lim) velocities[i][a] *= -1
        }
      }
      pGeo.attributes.position.needsUpdate = true
      rebuildLines()
      group.rotation.y += 0.0009
      group.rotation.x += 0.0004
      renderer.render(scene, camera)
      raf = requestAnimationFrame(tick)
    }
    rebuildLines()
    if (reduce) { renderer.render(scene, camera) } else { tick() }

    const onResize = () => {
      if (!mount) return
      w = mount.clientWidth; h = mount.clientHeight
      camera.aspect = w / h; camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      pGeo.dispose(); pMat.dispose(); lineGeo.dispose(); lineMat.dispose()
      renderer.dispose()
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement)
    }
  }, [])

  return <div id="login-canvas" ref={ref} />
}

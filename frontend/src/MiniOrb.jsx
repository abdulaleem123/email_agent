import React, { useEffect, useRef } from 'react'
import * as THREE from 'three'

/**
 * MiniOrb — a small, contained, always-on 3D accent (rotating wireframe
 * icosahedron + inner particle core) in brand colors. Used in every
 * section's intro card so the "3D module" feel is consistent everywhere,
 * not just the login page.
 *
 * Deliberately tiny (default 56px) and a single WebGL context per mounted
 * page (SPA renders one page at a time) — lightweight, won't tax the GPU
 * or hit the browser's WebGL-context limit even with heavy navigation.
 */
export default function MiniOrb({ size = 56, color = '#0054FC', accent = '#00BAFF' }) {
  const ref = useRef(null)

  useEffect(() => {
    const mount = ref.current
    if (!mount) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10)
    camera.position.z = 3.4

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setSize(size, size)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    mount.appendChild(renderer.domElement)

    const geo = new THREE.IcosahedronGeometry(1, 1)
    const wire = new THREE.LineSegments(
      new THREE.WireframeGeometry(geo),
      new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.85 })
    )
    scene.add(wire)

    const coreGeo = new THREE.IcosahedronGeometry(0.42, 0)
    const core = new THREE.Mesh(coreGeo, new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.55, wireframe: true }))
    scene.add(core)

    // small orbiting point-light-like dot for depth cue (no real lighting needed, MeshBasicMaterial is unlit)
    const dotGeo = new THREE.SphereGeometry(0.05, 8, 8)
    const dot = new THREE.Mesh(dotGeo, new THREE.MeshBasicMaterial({ color: accent }))
    scene.add(dot)

    let raf
    let t = 0
    const tick = () => {
      t += 0.012
      wire.rotation.y += 0.006
      wire.rotation.x += 0.003
      core.rotation.y -= 0.01
      dot.position.set(Math.cos(t) * 1.3, Math.sin(t * 1.3) * 0.5, Math.sin(t) * 1.3)
      renderer.render(scene, camera)
      raf = requestAnimationFrame(tick)
    }
    if (reduce) {
      renderer.render(scene, camera)
    } else {
      tick()
    }

    return () => {
      cancelAnimationFrame(raf)
      geo.dispose(); coreGeo.dispose(); dotGeo.dispose()
      wire.material.dispose(); core.material.dispose(); dot.material.dispose()
      renderer.dispose()
      if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement)
    }
  }, [size, color, accent])

  return <div ref={ref} style={{ width: size, height: size, flex: 'none' }} />
}
import { useEffect, useRef } from 'react';
import { useThree } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';

/**
 * Camera controls: left-drag=pan, scroll=zoom, right-drag=rotate (limited).
 * Double-click disabled to prevent accidental zoom resets.
 */
export function CameraControls() {
  const { camera } = useThree();
  const controlsRef = useRef<any>(null);

  useEffect(() => {
    camera.lookAt(-3, 0, -3);
    camera.updateProjectionMatrix();
    if (controlsRef.current) {
      controlsRef.current.target.set(-3, 0, -3);
      controlsRef.current.update();
    }
  }, [camera]);

  return (
    <OrbitControls
      ref={controlsRef}
      makeDefault
      target={[-3, 0, -3]}
      enableRotate={true}
      enablePan={true}
      enableZoom={true}
      screenSpacePanning={true}
      minZoom={8}
      maxZoom={25}
      minPolarAngle={Math.PI / 6}
      maxPolarAngle={Math.PI / 3}
      minAzimuthAngle={-Math.PI / 6}
      maxAzimuthAngle={Math.PI / 6}
      enableDamping={true}
      dampingFactor={0.08}
      panSpeed={1.0}
      zoomSpeed={1.2}
      rotateSpeed={0.4}
      // LEFT=pan(2), MIDDLE=dolly(1), RIGHT=rotate(0)
      mouseButtons={{ LEFT: 2, MIDDLE: 1, RIGHT: 0 }}
      // ONE finger=pan(1), TWO fingers=dolly+rotate(3)
      touches={{ ONE: 1, TWO: 3 }}
    />
  );
}

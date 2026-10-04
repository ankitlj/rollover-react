import { useEffect, useRef } from 'react';
import { ShaderRenderer, AURORA_VS, AURORA_FS, MESH_VS, MESH_FS } from '../shaders';

interface Props {
  variant: 'aurora' | 'mesh';
}

export default function ShaderBackground({ variant }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<ShaderRenderer | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const renderer = new ShaderRenderer(canvas);
    rendererRef.current = renderer;

    if (variant === 'aurora') {
      renderer.init(AURORA_VS, AURORA_FS);
    } else {
      renderer.init(MESH_VS, MESH_FS);
      renderer.palette = 0.0;
    }

    let active = true;
    renderer.startLoop(() => active);

    return () => {
      active = false;
      renderer.destroy();
      rendererRef.current = null;
    };
  }, [variant]);

  return <canvas ref={canvasRef} className="shader-bg" />;
}

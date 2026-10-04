import { useEffect, useRef } from 'react';
import { useStore } from '../store';

export default function TransitionScreen() {
  const { completeTransition } = useStore();
  const textRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const text = 'TRACK.TRADE.TRIUMPH';
    const el = textRef.current;
    if (!el) return;
    el.innerHTML = '';

    text.split('').forEach((char, i) => {
      const span = document.createElement('span');
      span.textContent = char === '.' ? '\u00b7' : char;
      span.style.opacity = '0';
      span.style.transform = 'translateY(30px) scale(0.8)';
      span.style.display = 'inline-block';
      span.style.transition = `all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) ${i * 0.06}s`;
      el.appendChild(span);
      requestAnimationFrame(() => {
        span.style.opacity = '1';
        span.style.transform = 'translateY(0) scale(1)';
      });
    });

    const timer = setTimeout(() => completeTransition(), 2400);
    return () => clearTimeout(timer);
  }, [completeTransition]);

  return (
    <div className="transition-screen">
      <div className="transition-content">
        <div className="transition-text" ref={textRef} />
        <div className="transition-bar">
          <div className="transition-bar-fill" />
        </div>
      </div>
    </div>
  );
}

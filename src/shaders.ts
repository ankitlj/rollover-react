export const AURORA_VS = `#version 300 es
in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }`;

export const AURORA_FS = `#version 300 es
precision highp float;
uniform float uTime;
uniform vec2 uResolution;
uniform vec2 uMouse;
uniform float uPalette;
out vec4 fragColor;

float curve(in vec2 p, in float fy, in float minLimit, in float maxLimit) {
  if(p.x < minLimit) return 0.0;
  if(p.x > maxLimit) return 0.0;
  float d = 1.0 - 300.0 * abs(p.y - fy);
  return clamp(d, 0.0, 1.0);
}

float nSin(in float t) {
  return 0.5 + 0.5 * sin(t);
}

float glowingPoint(in vec2 uv, in vec2 pos, in float size) {
  float dist = distance(uv, pos);
  float d = 1.0 - (1.0 / size) * dist;
  d = clamp(d, 0.0, 1.0);
  d = sqrt(sqrt(d));
  return d;
}

float speed = 0.15;
float trend = 1.5;

float stockFunction(in float x) {
  float t = x + uTime * speed;
  float s0 = sin(6.28 * t) * 0.4;
  float s1 = sin(3.68 * t) * 0.2;
  float s2 = sin(13.28 * t) * 0.1;
  float s3 = cos(32.43 * t) * 0.15;
  float s4 = sin(123.0 * t) * 0.1;
  float s5 = sin(331.0 * t) * 0.05;
  float s6 = sin(730.0 * t) * 0.035;
  float s7 = sin(1232.0 * t) * 0.02;
  float wave = s0 + s1 + s2 + s3 + s4 + s5 + s6 + s7;
  float modVal = mod(s1 * s2, 0.1) * (5.0 * sqrt(nSin(6.28 * t)));
  float final = wave + modVal;
  float fy = -trend / 1.5 + trend * x - 0.5 * final;
  return fy / 5.0;
}

float d_stockFunction(in float x, in float delta) {
  return (stockFunction(x - delta) - stockFunction(x)) / delta;
}

float longTrend(in float x) {
  return (d_stockFunction(x, 0.025) + d_stockFunction(x, 0.05) + d_stockFunction(x, 0.1)) / 3.0;
}

float shortTrend(in float x) {
  return (d_stockFunction(x, 0.004) + d_stockFunction(x, 0.005) + d_stockFunction(x, 0.006)) / 3.0;
}

vec3 trendColor(in float tr) {
  vec3 bull = vec3(0.063, 0.725, 0.506);
  vec3 bear = vec3(0.937, 0.267, 0.267);
  tr *= 100.0;
  tr = atan(tr) / 1.57079632679;
  tr += 1.0;
  tr /= 2.0;
  return mix(bull, bear, tr);
}

float gridFn(in vec2 uv, float tileSize, float borderSize) {
  float xMod = mod(uv.x, tileSize);
  float yMod = mod(uv.y, tileSize);
  if(xMod < borderSize || yMod < borderSize) return 1.0;
  return 0.0;
}

void main() {
  vec2 uv = gl_FragCoord.xy / uResolution.x;
  uv.y = uv.y - 0.33;
  vec3 base = vec3(0.02, 0.02, 0.035);
  vec2 gridOffset = vec2(uTime * speed, uTime * speed * trend / 5.0);
  vec3 gridCol = vec3(0.06, 0.06, 0.10) * gridFn(uv + gridOffset, 0.2, 0.002);
  vec3 line = trendColor(shortTrend(uv.x)) * curve(uv, stockFunction(uv.x), 0.0, 0.9);
  vec3 points = vec3(0.0);
  float size = 0.025;
  for(float offset = 0.0; offset < 1.0; offset += 0.05) {
    float pos = 0.9 + (0.85 - 0.9) * offset;
    vec3 pColor = glowingPoint(uv, vec2(pos, stockFunction(pos)), size) * trendColor(longTrend(pos));
    points = max(points, pColor);
    size *= 0.92;
  }
  vec3 color = max(line * 0.8, points * 0.6) + gridCol * 0.05;
  color += base;
  vec2 vigUV = gl_FragCoord.xy / uResolution - 0.5;
  float vig = 1.0 - dot(vigUV, vigUV) * 1.4;
  color *= vig;
  color *= 0.97 + 0.03 * sin(gl_FragCoord.y * 1.5 + uTime * 2.0);
  vec2 mUV = uMouse;
  float mDist = length(gl_FragCoord.xy / uResolution - mUV);
  color += vec3(0.04, 0.05, 0.10) * exp(-mDist * 4.0) * 0.3;
  fragColor = vec4(color, 1.0);
}`;

export const MESH_VS = `#version 300 es
in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }`;

export const MESH_FS = `#version 300 es
precision highp float;
uniform float uTime;
uniform vec2 uResolution;
uniform vec2 uMouse;
uniform float uPalette;
out vec4 fragColor;

mat2 rot2(float a){float s=sin(a),c=cos(a);return mat2(c,-s,s,c);}

float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}

float noise(vec2 p){
  vec2 i=floor(p),f=fract(p);
  f=f*f*(3.0-2.0*f);
  return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);
}

float fbm(vec2 p){
  float v=0.0,a=0.5;
  for(int i=0;i<5;i++){v+=a*noise(p);p=rot2(0.42)*p*2.0;a*=0.5;}
  return v;
}

void main(){
  vec2 uv=gl_FragCoord.xy/uResolution;
  float t=uTime*0.06;
  vec2 q=vec2(fbm(uv*2.0+vec2(t*0.3,t*0.2)),fbm(uv*2.0+vec2(-t*0.2,t*0.35)));
  float f=fbm(uv*2.5+q*1.5);
  float f2=fbm(uv*3.5+q*0.8+vec2(t*0.1));
  vec3 c1=vec3(0.035,0.035,0.05);
  vec3 c2=vec3(0.06,0.06,0.10);
  vec3 c3=vec3(0.05,0.04,0.09);
  vec3 c4=vec3(0.04,0.05,0.08);
  vec3 col=mix(c1,c2,f);
  col=mix(col,c3,f2*0.4);
  col=mix(col,c4,noise(uv*8.0+t)*0.15);
  float glow=exp(-length(uv-uMouse)*5.0)*0.04;
  col+=vec3(0.08,0.08,0.15)*glow;
  float caustic=pow(noise(uv*6.0+q*2.0+t),3.0)*0.03;
  col+=vec3(0.06,0.06,0.12)*caustic;
  fragColor=vec4(col,0.4);
}`;

export class ShaderRenderer {
  canvas: HTMLCanvasElement;
  gl: WebGL2RenderingContext | null;
  program!: WebGLProgram | null;
  vao!: WebGLVertexArrayObject | null;
  startTime!: number;
  mouse!: [number, number];
  resolution!: [number, number];
  palette!: number;
  uTime!: WebGLUniformLocation | null;
  uRes!: WebGLUniformLocation | null;
  uMouse!: WebGLUniformLocation | null;
  uPalette!: WebGLUniformLocation | null;
  private _animId: number | null = null;
  private _resizeHandler!: () => void;
  private _mouseHandler!: (e: MouseEvent) => void;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.gl = canvas.getContext('webgl2', { alpha: true, premultipliedAlpha: false, antialias: true });
    if (!this.gl) { console.warn('WebGL2 not available'); return; }
    const gl = this.gl;
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this.program = null;
    this.vao = null;
    this.startTime = performance.now();
    this.mouse = [0, 0];
    this.resolution = [1, 1];
    this.palette = 0;
    this.uTime = null;
    this.uRes = null;
    this.uMouse = null;
    this.uPalette = null;

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);
    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    const loc = 0;
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);

    this._resize();
    this._resizeHandler = () => this._resize();
    this._mouseHandler = (e: MouseEvent) => {
      this.mouse[0] = e.clientX / window.innerWidth;
      this.mouse[1] = 1.0 - e.clientY / window.innerHeight;
    };
    window.addEventListener('resize', this._resizeHandler);
    window.addEventListener('mousemove', this._mouseHandler);
  }

  _resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = window.innerWidth * dpr;
    this.canvas.height = window.innerHeight * dpr;
    this.canvas.style.width = window.innerWidth + 'px';
    this.canvas.style.height = window.innerHeight + 'px';
    this.resolution = [this.canvas.width, this.canvas.height];
    if (this.gl) this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
  }

  compile(type: number, src: string): WebGLShader | null {
    const gl = this.gl;
    if (!gl) return null;
    const s = gl.createShader(type);
    if (!s) return null;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.error('Shader compile error:', gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    }
    return s;
  }

  init(vsSrc: string, fsSrc: string) {
    const gl = this.gl;
    if (!gl) return;
    const vs = this.compile(gl.VERTEX_SHADER, vsSrc);
    const fs = this.compile(gl.FRAGMENT_SHADER, fsSrc);
    if (!vs || !fs) return;
    this.program = gl.createProgram();
    if (!this.program) return;
    gl.attachShader(this.program, vs);
    gl.attachShader(this.program, fs);
    gl.bindAttribLocation(this.program, 0, 'aPos');
    gl.linkProgram(this.program);
    if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) {
      console.error('Program link error:', gl.getProgramInfoLog(this.program));
      return;
    }
    gl.deleteShader(vs);
    gl.deleteShader(fs);
    this.uTime = gl.getUniformLocation(this.program, 'uTime');
    this.uRes = gl.getUniformLocation(this.program, 'uResolution');
    this.uMouse = gl.getUniformLocation(this.program, 'uMouse');
    this.uPalette = gl.getUniformLocation(this.program, 'uPalette');
  }

  render() {
    const gl = this.gl;
    if (!gl || !this.program) return;
    gl.useProgram(this.program);
    gl.uniform1f(this.uTime!, (performance.now() - this.startTime) * 0.001);
    gl.uniform2f(this.uRes!, this.resolution[0], this.resolution[1]);
    gl.uniform2f(this.uMouse!, this.mouse[0], this.mouse[1]);
    gl.uniform1f(this.uPalette!, this.palette);
    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.bindVertexArray(null);
  }

  startLoop(shouldContinue: () => boolean) {
    const loop = () => {
      if (!shouldContinue()) return;
      this.render();
      this._animId = requestAnimationFrame(loop);
    };
    loop();
  }

  destroy() {
    if (this._animId) cancelAnimationFrame(this._animId);
    window.removeEventListener('resize', this._resizeHandler);
    window.removeEventListener('mousemove', this._mouseHandler);
    if (this.gl && this.program) {
      this.gl.deleteProgram(this.program);
      this.program = null;
    }
  }
}

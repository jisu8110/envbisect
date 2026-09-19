// Executable oracle for nodejs/node#65601.
const args = Object.fromEntries(process.argv.slice(2).map((x) => x.replace(/^--/, '').split('=')));
const size = Number(args.size ?? 8);
const allocation = args.allocation ?? 'pooled';
const length = args.length ?? 'implicit';
const width = Number(args.width ?? 32);
if (!Number.isInteger(size) || size < 0 || !['pooled', 'slow'].includes(allocation) ||
    !['implicit', 'explicit'].includes(length) || ![8, 16, 32].includes(width)) {
  throw new Error('invalid fixture arguments');
}
const buffer = allocation === 'pooled' ? Buffer.allocUnsafe(size) : Buffer.allocUnsafeSlow(size);
const Type = {8: Uint8Array, 16: Uint16Array, 32: Uint32Array}[width];
const start = process.hrtime.bigint();
let error = null;
let viewLength = null;
try {
  const view = length === 'explicit'
    ? new Type(buffer.buffer, buffer.byteOffset, Math.floor(size / Type.BYTES_PER_ELEMENT))
    : new Type(buffer.buffer, buffer.byteOffset);
  viewLength = view.length;
} catch (e) {
  error = `${e.name}: ${e.message}`;
}
const elapsedMs = Number(process.hrtime.bigint() - start) / 1e6;
const result = {
  node: process.version,
  size, allocation, length, width,
  backingLength: buffer.buffer.byteLength,
  byteOffset: buffer.byteOffset,
  viewLength,
  status: error === null ? 'PASS' : 'FAIL',
  error,
  elapsedMs: Number(elapsedMs.toFixed(4)),
};
console.log(JSON.stringify(result));
process.exitCode = error === null ? 0 : 1;

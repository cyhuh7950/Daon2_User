export function packNativeResponse(body, { status = 200, headers = [["content-type", "application/json"]] } = {}) {
  const metadata = new TextEncoder().encode(JSON.stringify([status, headers]));
  const payload = typeof body === "string" ? new TextEncoder().encode(body) : new Uint8Array(body);
  const bytes = new Uint8Array(4 + metadata.length + payload.length);
  new DataView(bytes.buffer).setUint32(0, metadata.length, true);
  bytes.set(metadata, 4);
  bytes.set(payload, 4 + metadata.length);
  return bytes.buffer;
}

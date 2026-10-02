// Electron wraps an error thrown in a main-process handler as
// "Error invoking remote method 'mr:approve': Error: <real message>". Show the real one.
export function cleanIpcError(err) {
  const text = String(err?.message ?? err)
  return text.replace(/^Error invoking remote method '[^']+':\s*(Error:\s*)?/, '')
}

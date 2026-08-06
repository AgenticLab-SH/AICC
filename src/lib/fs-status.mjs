import fs from 'node:fs';

export function pathStatus(path) {
  try {
    const stat = fs.statSync(path);
    return {
      path,
      exists: true,
      kind: stat.isDirectory() ? 'directory' : stat.isFile() ? 'file' : 'other',
      modifiedAt: stat.mtime.toISOString()
    };
  } catch {
    return { path, exists: false, kind: null, modifiedAt: null };
  }
}

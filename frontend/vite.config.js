import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('.', import.meta.url));
function runtimeLicenses() {
  const store = path.join(root, 'node_modules/.pnpm');
  const packages = [
    'react',
    'react-dom',
    'scheduler',
    'three',
    'lucide-react',
    'motion',
    'framer-motion',
    'motion-dom',
    'motion-utils',
  ];
  return packages
    .map((name) => {
      let directory = path.join(root, 'node_modules', name);
      if (!fs.existsSync(directory)) {
        const entry = fs.readdirSync(store).find((folder) => folder.startsWith(name + '@'));
        directory = path.join(store, entry, 'node_modules', name);
      }
      const license = fs
        .readdirSync(directory)
        .find((file) => /^license(?:\.md|\.txt)?$/i.test(file));
      if (!license) throw new Error('Missing runtime license: ' + name);
      const metadata = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'));
      return (
        name +
        ' ' +
        metadata.version +
        '\n\n' +
        fs.readFileSync(path.join(directory, license), 'utf8')
      );
    })
    .join('\n\n========================================\n\n');
}

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'runtime-licenses',
      generateBundle() {
        this.emitFile({ type: 'asset', fileName: 'licenses.txt', source: runtimeLicenses() });
      },
    },
  ],
  base: '/assets/',
  publicDir: false,
  server: {
    port: 18766,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:18765',
      '^/assets/(?:manrope-latin\\.woff2|noto-ui\\.woff2|edge-mark\\.svg|edge-glass\\.webp)$':
        'http://127.0.0.1:18765',
    },
  },
  build: {
    outDir: '../master/ui',
    emptyOutDir: true,
    assetsDir: '',
    rollupOptions: {
      output: {
        entryFileNames: 'panel.js',
        chunkFileNames: '[name]-[hash].js',
        assetFileNames: 'panel[extname]',
      },
    },
  },
});

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) } },
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    outDir: '../.local/tag-picker-fixture', emptyOutDir: true,
    lib: { entry: 'checks/tag-picker-fixture.tsx', name: 'TagPickerProbe', formats: ['iife'], fileName: () => 'probe.js' },
  },
})

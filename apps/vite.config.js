import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => ({
    plugins: [react()],
    server: {
        host: '0.0.0.0',
        port: 3000,
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                // 后端 graph/knowledge 等路由无前缀 /api；但 document_insight、hybrid_search 使用 prefix=/api/v1，须保留 /api/v1。
                rewrite: (path) => {
                    const out = path.startsWith('/api/v1') ? path : path.replace(/^\/api/, '')
                    if (mode === 'development' && out !== path) {
                        console.log('[vite-proxy]', path, '→', out)
                    }
                    return out
                },
            },
        },
    },
}))

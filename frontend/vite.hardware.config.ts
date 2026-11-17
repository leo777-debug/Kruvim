import { defineConfig } from "vite";
import path from "node:path";
export default defineConfig({base:"./",worker:{format:"es"},build:{outDir:"../../kruvim-paid-local-followup-20261117/hardware-package",emptyOutDir:false,rollupOptions:{input:path.resolve(__dirname,"hardware-check/index.html")}}});

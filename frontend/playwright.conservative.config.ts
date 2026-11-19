import { defineConfig } from '@playwright/test';
import base from './playwright.config';
export default defineConfig({webServer:base.webServer,testDir:'./e2e',testMatch:'local-conservative.spec.ts',timeout:120000,workers:1,retries:0,outputDir:'test-results-conservative',use:{baseURL:'http://127.0.0.1:5186',trace:'retain-on-failure'},projects:[{name:'conservative',use:{channel:process.env.KRUVIM_BROWSER_CHANNEL||undefined}}]});

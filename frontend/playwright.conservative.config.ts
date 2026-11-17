import { defineConfig } from '@playwright/test';
export default defineConfig({testDir:'./e2e',testMatch:'local-conservative.spec.ts',timeout:120000,workers:1,retries:0,outputDir:'test-results-conservative',use:{baseURL:'http://127.0.0.1:5186',trace:'retain-on-failure'},projects:[{name:'edge',use:{channel:'msedge'}},{name:'chrome',use:{channel:'chrome'}}]});

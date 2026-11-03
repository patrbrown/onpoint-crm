/** @type {import('next').NextConfig} */
// The desktop Docker image uses a self-contained "standalone" build; Netlify does its own packaging.
const nextConfig = { reactStrictMode: true, ...(process.env.NEXT_OUTPUT === "standalone" ? { output: "standalone" } : {}) };
export default nextConfig;

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  experimental: { authInterrupts: true },
  transpilePackages: ["@daon2-user/ui", "@daon2-user/design-tokens", "@daon2-user/contracts"]
};

export default nextConfig;

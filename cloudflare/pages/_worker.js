/**
 * Proxy de Cloudflare Pages hacia la app Flask alojada en Render.
 *
 * Permite publicar la demo en https://asistencias-casaperu.pages.dev
 * manteniendo el backend Python (base de datos, marcaciones, etc.).
 */
const ORIGIN = "https://asistencias-casaperu.onrender.com";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = ORIGIN + url.pathname + url.search;

    const headers = new Headers(request.headers);
    for (const h of [
      "host", "connection", "keep-alive",
      "cf-connecting-ip", "cf-ipcountry", "cf-ray", "cf-visitor",
      "x-forwarded-proto", "x-forwarded-for", "x-real-ip",
    ]) {
      headers.delete(h);
    }

    const init = { method: request.method, headers, redirect: "manual" };
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
    }

    const resp = await fetch(target, init);

    const out = new Headers(resp.headers);
    for (const h of [
      "content-encoding", "content-length", "transfer-encoding",
      "connection", "keep-alive",
    ]) {
      out.delete(h);
    }

    return new Response(resp.body, {
      status: resp.status,
      statusText: resp.statusText,
      headers: out,
    });
  },
};

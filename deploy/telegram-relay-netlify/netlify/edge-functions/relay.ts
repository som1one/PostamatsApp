// Ретранслятор Telegram Bot API для прода naprokatberu.
//
// С VPS в РФ не открываются ни api.telegram.org, ни Cloudflare (*.workers.dev),
// а *.netlify.app открывается. Контракт тот же, что у прежнего Worker'а —
// бэкенду меняется только TELEGRAM_RELAY_URL (backend/utils/telegram_transport.py):
//
//   POST/GET /api/<method>  + Authorization: Bearer <RELAY_SECRET>
//       → https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/<method>
//       тело (JSON или multipart с фото) и Content-Type передаются как есть.
//   POST /webhook
//       → BACKEND_WEBHOOK_URL (https://api.naprokatberu.ru/telegram/webhook/<secret>)
//       с заголовком X-Telegram-Bot-Api-Secret-Token; бэкенд проверяет его сам.
//
// Переменные окружения задаются в Netlify: Site configuration → Environment variables.

declare const Netlify: { env: { get(name: string): string | undefined } };

const TELEGRAM_API = "https://api.telegram.org";
const METHOD_RE = /^[A-Za-z]{1,64}$/;

function env(name: string): string {
  return (Netlify.env.get(name) ?? "").trim();
}

function text(status: number, body: string): Response {
  return new Response(body, {
    status,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}

async function readBody(req: Request): Promise<ArrayBuffer | undefined> {
  if (req.method === "GET" || req.method === "HEAD") return undefined;
  return await req.arrayBuffer();
}

async function relayApi(req: Request, url: URL): Promise<Response> {
  const token = env("TELEGRAM_BOT_TOKEN");
  const secret = env("RELAY_SECRET");
  if (!token || !secret) return text(503, "relay is not configured");
  if (req.headers.get("authorization") !== `Bearer ${secret}`) {
    return text(401, "unauthorized");
  }

  const method = url.pathname.slice("/api/".length);
  if (!METHOD_RE.test(method)) return text(400, "bad method");

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  try {
    const upstream = await fetch(`${TELEGRAM_API}/bot${token}/${method}${url.search}`, {
      method: req.method,
      headers,
      body: await readBody(req),
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    return text(502, `telegram unreachable: ${String(error).slice(0, 200)}`);
  }
}

async function relayWebhook(req: Request): Promise<Response> {
  const target = env("BACKEND_WEBHOOK_URL");
  if (!target) return text(503, "webhook target is not configured");

  const headers = new Headers({
    "content-type": req.headers.get("content-type") ?? "application/json",
  });
  const telegramSecret = req.headers.get("x-telegram-bot-api-secret-token");
  if (telegramSecret) headers.set("x-telegram-bot-api-secret-token", telegramSecret);

  try {
    const upstream = await fetch(target, {
      method: "POST",
      headers,
      body: await req.arrayBuffer(),
    });
    return new Response(upstream.body, { status: upstream.status });
  } catch (error) {
    return text(502, `backend unreachable: ${String(error).slice(0, 200)}`);
  }
}

export default async (req: Request): Promise<Response> => {
  const url = new URL(req.url);
  if (url.pathname.startsWith("/api/")) return relayApi(req, url);
  if (url.pathname === "/webhook" && req.method === "POST") return relayWebhook(req);
  return text(404, "not found");
};

export const config = { path: "/*" };

import { NextResponse } from "next/server";

type DemoRequestPayload = {
  name?: string;
  email?: string;
  company?: string;
  role?: string;
};

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export async function POST(request: Request) {
  let body: DemoRequestPayload;
  try {
    body = (await request.json()) as DemoRequestPayload;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const name = (body.name ?? "").toString().trim();
  const email = (body.email ?? "").toString().trim();
  const company = (body.company ?? "").toString().trim();
  const role = (body.role ?? "").toString().trim();

  if (!name || !email || !company || !role) {
    return NextResponse.json({ error: "All fields are required." }, { status: 400 });
  }
  if (!isValidEmail(email)) {
    return NextResponse.json({ error: "Please provide a valid work email." }, { status: 400 });
  }
  if (name.length > 200 || email.length > 200 || company.length > 200 || role.length > 200) {
    return NextResponse.json({ error: "Field too long." }, { status: 400 });
  }

  console.log(
    JSON.stringify({
      event: "demo_request",
      name,
      email,
      company,
      role,
      at: new Date().toISOString(),
    }),
  );

  return NextResponse.json({ accepted: true }, { status: 202 });
}

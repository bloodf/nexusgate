import { NextRequest, NextResponse } from "next/server";
import { ubusCall } from "@/lib/ubus-client";
export async function POST(req:NextRequest){const body=await req.json();const data=await ubusCall(body.object,body.method,body.params);return NextResponse.json(data)}

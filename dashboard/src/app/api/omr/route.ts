import { NextRequest, NextResponse } from "next/server";
import { omr } from "@/lib/omr-client";
export async function GET(req:NextRequest){const path=req.nextUrl.searchParams.get("path")??"/";return NextResponse.json(await omr(path))}
export async function POST(req:NextRequest){const body=await req.json();return NextResponse.json(await omr(body.path??"/",{method:"POST",body:JSON.stringify(body.payload??{})}))}

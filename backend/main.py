import json
import sqlite3
import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "components.db"

def get_all_components():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT part_name, category, price, bug_details, summary_text FROM components")
    rows = cursor.fetchall()
    conn.close()
    
    components = []
    for row in rows:
        components.append({
            "part_name": row[0],
            "category": row[1],
            "price": row[2],
            "bug_details": row[3],
            "summary": row[4][:1000] if row[4] else "" # Truncate summary to save tokens
        })
    return components

@app.post("/api/generate")
async def generate_scheme(
    file: UploadFile = File(...),
    api_key: str = Form(...)
):
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenRouter API key is required.")
        
    try:
        content = await file.read()
        requirements = content.decode('utf-8')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {e}")
        
    components = get_all_components()
    components_json = json.dumps(components, indent=2)

    prompt = f"""
You are an expert power electronics engineer. The user has provided the following electrical requirements for a power scheme:
{requirements}

Here is a list of available components in the database, including their category, price, known bugs, and a summary of their datasheet specs:
{components_json}

CRITICAL constraint instructions:
1. Use buck converter & LDO's. For LDO, buck converter output voltage rails should be used as input.
2. Ensure the in-direct load current also added to respective source load for both buck & LDO.
3. Provide the thermal rise (estimated junction temperature value) based on worst case efficiency for buck converter and LDO's & consider thermal resistance value from data sheet.
4. Calculate and verify the PSRR (Power Supply Rejection Ratio) and Voltage ripple by reading from the data sheets and add the same in combined power scheme comparison and final summary.
5. Add the switching frequency in the combined power scheme comparison and final summary.
6. Use splitting into multiple smaller converters if thermal constraints failed, consider the space constraints and size of the converter if required use different converters.
7. While selecting buck or LDO consider 1.5 to 1.75 times deration in current rating.
8. While choosing the input voltage for LDO consider for minimum dropout voltage requirement and drop out voltage should be minimum.
10. CRITICAL: Buck Converters like the LTM4638 are strictly SINGLE-OUTPUT devices. They can only generate ONE voltage level out. If the requirement specifies multiple different voltage rails (e.g., 8 different outputs), you CANNOT draw them coming directly from a single LTM4638. You MUST use multiple discrete Buck Converters or use the Buck Converter's single output as the source for multiple distinct LDO regulators in a distribution tree.
11. Provide EXACTLY THREE different combined power schemes.
12. IMPORTANT DIAGRAM RULE: When generating the schematics_mermaid code, you MUST use the exact IC Part Number / Controller Name as the label for each node (e.g., use A[LTM4638] or A[TPS73701DCQ LDO] instead of generic names like A[Buck Converter] or A[LDO]).
13. MANDATORY: The 'rail_analysis' array MUST contain a detailed engineering object for EVERY voltage rail specified in the input requirements (e.g., if there are 8 rails, there must be 8 items in the array).
14. CALCULATION RULE: For each rail, the 'calculation' string MUST show the formula (e.g., V_rip = I_out / (8*f*C)) and the specific values used for that specific rail.
15. JSON SAFETY: Do NOT use raw backslashes (\\) or complex markdown symbols in any string. Use standard division (/) and multiplication (*). Ensure all string quotes are correctly escaped.

Return ONLY a valid JSON response matching this schema exactly:
{{
    "final_summary": "Extensive comparison of the 3 schemes including price, number of bucks/LDOs, and thermal performance.",
    "schemes": [
        {{
            "scheme_name": "Scheme Option Name",
            "total_price": 0.0,
            "selected_components": [
                {{ "part_name": "...", "reasoning": "...", "price": 0.0 }}
            ],
            "rail_analysis": [
                {{ 
                   "rail": "V1 (3.3V)", 
                   "component": "LTM4638",
                   "ripple": {{ "calculation": "V_rip = 6A / (8 * 1.5MHz * 22uF)", "value": "12mV", "status": "Pass" }},
                   "psrr": {{ "calculation": "Datasheet: 45dB min at 1.5MHz", "value": "45dB", "status": "Pass" }},
                   "thermal": {{ "calculation": "Tj = 85C + (1.2W * 25C/W)", "value": "115C", "status": "Pass" }}
                }}
            ],
            "switching_frequency": "1.5MHz",
            "schematics_mermaid": "graph TD A[...]"
        }}
    ]
}}
"""


    try:
        client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        
        response = await client.chat.completions.create(
            # Auto-route to any available free model to prevent 404s
            model="openrouter/free", 
            messages=[
                {"role": "system", "content": "You are a helpful JSON-only outputting assistant. You must output valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            extra_headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Power Scheme Generator"
            }
        )
        
        result_text = response.choices[0].message.content
        # Robustly extract JSON content from potentially messy LLM response
        try:
            start_idx = result_text.find("{")
            end_idx = result_text.rfind("}")
            if start_idx != -1 and end_idx != -1:
                result_text = result_text[start_idx:end_idx+1]
            
            result_json = json.loads(result_text)
            return JSONResponse(content=result_json)
        except Exception as parse_err:
            print(f"DEBUG: Raw result text was: {result_text}")
            raise HTTPException(status_code=500, detail=f"JSON Parse Error: {str(parse_err)}")
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM Error: {str(e)}\n\nPrompt Response: {result_text if 'result_text' in locals() else ''}")

# Serve frontend with no-cache headers to always deliver latest files
@app.get("/")
def read_index():
    return FileResponse("frontend/index.html", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache"
    })

@app.get("/static/{file_path:path}")
def serve_static(file_path: str):
    full_path = f"frontend/{file_path}"
    return FileResponse(full_path, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache"
    })

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

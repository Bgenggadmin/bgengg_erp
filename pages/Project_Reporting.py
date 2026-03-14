def generate_pdf(logs):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # 1. FIX: Fetch logo and give it a dummy name so FPDF doesn't crash on 'rfind'
    logo_stream = None
    try:
        logo_data = conn.client.storage.from_("progress-photos").download("logo.png")
        if logo_data:
            logo_stream = BytesIO(logo_data)
            logo_stream.name = "logo.png" # <--- THIS PREVENTS THE rfind ERROR
    except:
        pass

    for log in logs:
        pdf.add_page()
        
        # --- HEADER STRIP (Restored) ---
        pdf.set_fill_color(0, 51, 102) 
        pdf.rect(0, 0, 210, 25, 'F')
        
        if logo_stream:
            try:
                logo_stream.seek(0)
                pdf.image(logo_stream, x=12, y=5, h=15)
            except:
                pass

        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Arial", "B", 16)
        pdf.set_xy(70, 5) 
        pdf.cell(130, 10, "B&G ENGINEERING INDUSTRIES", 0, 1, "L")
        pdf.set_font("Arial", "I", 10)
        pdf.set_xy(70, 14)
        pdf.cell(130, 5, "PROJECT PROGRESS REPORT", 0, 1, "L")
        
        # --- JOB HEADER (Restored) ---
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "B", 10)
        pdf.set_xy(10, 30)
        pdf.cell(0, 8, f" JOB: {log.get('job_code','')} | ID: {log.get('id','')}", "B", 1, "L")
        pdf.ln(2)
        
        # --- FIELD GRID (Restored with Gray Background) ---
        pdf.set_font("Arial", "B", 8)
        pdf.set_fill_color(240, 240, 240)
        for i in range(0, len(HEADER_FIELDS), 2):
            f1, f2 = HEADER_FIELDS[i], HEADER_FIELDS[i+1]
            # Safety check for None values
            v1 = str(log.get(f1)) if log.get(f1) is not None else "-"
            v2 = str(log.get(f2)) if log.get(f2) is not None else "-"
            
            pdf.cell(30, 7, f" {f1.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.set_font("Arial", "", 8)
            pdf.cell(65, 7, f" {v1}", 1, 0, 'L')
            pdf.set_font("Arial", "B", 8)
            pdf.cell(30, 7, f" {f2.replace('_',' ').title()}", 1, 0, 'L', True)
            pdf.set_font("Arial", "", 8)
            pdf.cell(65, 7, f" {v2}", 1, 1, 'L')

        pdf.ln(5)

        # --- MILESTONE TABLE (Restored with Colors & Remarks) ---
        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(0, 51, 102); pdf.set_text_color(255, 255, 255)
        pdf.cell(60, 8, " Milestone Item", 1, 0, 'L', True)
        pdf.cell(35, 8, " Status", 1, 0, 'C', True)
        pdf.cell(95, 8, " Remarks", 1, 1, 'L', True)
        
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", "", 8)
        for label, s_key, n_key in MILESTONE_MAP:
            status = str(log.get(s_key, 'Pending'))
            # Restored Color Logic
            if status in ["Completed", "Approved", "Submitted"]: pdf.set_fill_color(144, 238, 144)
            elif status in ["In-Progress", "Hold", "Ordered", "Received", "Planning", "Scheduled"]: pdf.set_fill_color(255, 255, 204)
            else: pdf.set_fill_color(255, 255, 255)
            
            pdf.cell(60, 7, f" {label}", 1)
            pdf.cell(35, 7, f" {status}", 1, 0, 'C', True)
            pdf.cell(95, 7, f" {str(log.get(n_key,'-'))}", 1, 1)

        # --- PROGRESS PHOTO (Restored) ---
        try:
            img_url = conn.client.storage.from_("progress-photos").get_public_url(f"{log['id']}.jpg")
            img_res = requests.get(img_url, timeout=3)
            if img_res.status_code == 200:
                img = Image.open(BytesIO(img_res.content)).convert('RGB')
                img.thumbnail((350, 350))
                buf = BytesIO()
                img.save(buf, format="JPEG")
                buf.name = "progress.jpg" # <--- Fix for image crash
                buf.seek(0)
                pdf.image(buf, x=75, y=pdf.get_y()+10, w=60)
        except: 
            pass

    return bytes(pdf.output())

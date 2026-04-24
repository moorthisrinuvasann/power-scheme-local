import os
import sqlite3
import PyPDF2
import pandas as pd

def extract_pdf_text(filepath, max_pages=3):
    text = ""
    try:
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            num_pages = min(len(reader.pages), max_pages)
            for i in range(num_pages):
                page_text = reader.pages[i].extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
    return text

def main():
    db_path = 'components.db'
    if os.path.exists(db_path):
        os.remove(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part_name TEXT,
            category TEXT,
            price REAL,
            bug_details TEXT,
            summary_text TEXT
        )
    ''')
    
    # Load price details
    df = pd.read_excel('datasheets/pricedetails.xlsx')
    
    price_dict = {}
    bug_dict = {}
    
    buck_mode = True
    for index, row in df.iterrows():
        try:
            val = str(row.iloc[1]).strip()
            if 'LDO' in str(row.iloc[0]):
                buck_mode = False
                continue
            if pd.isna(row.iloc[1]) or val == 'Part No' or val == 'nan':
                continue
            
            part_no = val
            price = row.iloc[2]
            bug = row.iloc[3]
            price_dict[part_no] = float(price) if not pd.isna(price) else 0.0
            bug_dict[part_no] = str(bug) if not pd.isna(bug) else ""
        except:
            pass

    # Process PDFs
    base_dir = 'datasheets'
    categories = ['BuckConverter', 'LDO']
    
    for category in categories:
        cat_dir = os.path.join(base_dir, category)
        if not os.path.exists(cat_dir):
            continue
            
        for file in os.listdir(cat_dir):
            if file.endswith('.pdf'):
                part_name = file.replace('.pdf', '').upper()
                # matching with price dict
                matched_part = part_name
                for p in price_dict.keys():
                    if part_name in p or p in part_name:
                        matched_part = p
                        break
                
                price = price_dict.get(matched_part, 0.0)
                bug = bug_dict.get(matched_part, "")
                
                print(f"Ingesting {file} as {matched_part} in {category}...")
                text = extract_pdf_text(os.path.join(cat_dir, file), max_pages=3)
                
                cursor.execute('''
                    INSERT INTO components (part_name, category, price, bug_details, summary_text)
                    VALUES (?, ?, ?, ?, ?)
                ''', (matched_part, category, price, bug, text))
                
    conn.commit()
    conn.close()
    print("Database creation complete.")

if __name__ == '__main__':
    main()

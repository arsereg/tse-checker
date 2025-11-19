import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
from flask import Flask, request, jsonify

def get_tse_details_html(cedula):
    """
    Retrieves the HTML content of the TSE detailed birth information page.
    
    Args:
        cedula (str): The ID number to search (e.g., "102920417")
    
    Returns:
        str: The HTML content of the detailed page
    """
    
    # Create a session with retry strategy for robustness
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    base_url = "https://servicioselectorales.tse.go.cr/chc"
    search_url = f"{base_url}/consulta_cedula.aspx"
    
    try:
        # Step 1: Get initial page to extract ViewState and other hidden fields
        print(f"Step 1: Fetching initial form from {search_url}")
        response = session.get(search_url)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract ViewState and other ASP.NET hidden fields
        viewstate = soup.find('input', {'name': '__VIEWSTATE'})
        viewstategenerator = soup.find('input', {'name': '__VIEWSTATEGENERATOR'})
        eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})
        
        hidden_fields = {
            '__VIEWSTATE': viewstate['value'] if viewstate else '',
            '__VIEWSTATEGENERATOR': viewstategenerator['value'] if viewstategenerator else '',
            '__EVENTVALIDATION': eventvalidation['value'] if eventvalidation else '',
        }
        
        # Step 2: Submit the search form with the cedula number
        print(f"Step 2: Searching for cedula {cedula}")
        search_data = {
            'txtcedula': cedula,
            'btnConsultaCedula': 'Consultar',
            **hidden_fields
        }
        
        response = session.post(search_url, data=search_data)
        response.raise_for_status()
        
        # Step 3: Parse the results page and extract ViewState again
        print("Step 3: Parsing results page")
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract new ViewState from results page
        viewstate = soup.find('input', {'name': '__VIEWSTATE'})
        viewstategenerator = soup.find('input', {'name': '__VIEWSTATEGENERATOR'})
        eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})
        
        new_hidden_fields = {
            '__VIEWSTATE': viewstate['value'] if viewstate else '',
            '__VIEWSTATEGENERATOR': viewstategenerator['value'] if viewstategenerator else '',
            '__EVENTVALIDATION': eventvalidation['value'] if eventvalidation else '',
        }
        
        # Step 4: Click "Ver Más Detalles" (LinkButton11)
        print("Step 4: Clicking 'Ver Más Detalles' link")
        result_url = f"{base_url}/resultado_persona.aspx"
        
        details_data = {
            '__EVENTTARGET': 'LinkButton11',
            '__EVENTARGUMENT': '',
            **new_hidden_fields
        }
        
        response = session.post(result_url, data=details_data)
        response.raise_for_status()
        
        # Step 5: Get the detailed page
        print("Step 5: Retrieved detailed information page")
        details_html = response.text
        
        return details_html
        
    except requests.RequestException as e:
        print(f"Error during request: {e}")
        raise
    except Exception as e:
        print(f"Error processing response: {e}")
        raise


def parse_details_from_html(html_content):
    """
    Parses the detailed information from the HTML content.

    Args:
        html_content (str): The HTML content of the details page

    Returns:
        dict: Dictionary containing extracted information
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    details = {}

    # Find all labels and their corresponding values
    labels = soup.find_all('td', class_='label')
    for label in labels:
        label_text = label.get_text(strip=True)
        # Try to find the next td that contains the value
        next_td = label.find_next('td')
        if next_td:
            value = next_td.get_text(strip=True)
            details[label_text] = value

    return details


def check_fallecido(cedula):
    """
    Checks if a person is deceased based on their cedula.

    Args:
        cedula (str): The ID number to search

    Returns:
        dict: Dictionary with 'fallecido' key (True/False) or error information
    """
    try:
        # Retrieve the HTML
        html_content = get_tse_details_html(cedula)

        # Parse the HTML to extract the fallecido value
        soup = BeautifulSoup(html_content, 'html.parser')
        fallecido_span = soup.find('span', {'id': 'lblfallecido'})

        if fallecido_span:
            fallecido_value = fallecido_span.get_text(strip=True).upper()

            # Return TRUE if "SI", FALSE if "NO"
            if fallecido_value == "SI":
                return {"fallecido": True, "cedula": cedula}
            elif fallecido_value == "NO":
                return {"fallecido": False, "cedula": cedula}
            else:
                return {"error": f"Unknown value for Fallecido/a: {fallecido_value}"}
        else:
            return {"error": "Could not find 'lblfallecido' element in HTML"}

    except Exception as e:
        return {"error": str(e)}


# Create Flask app
app = Flask(__name__)

@app.route('/check', methods=['GET'])
def check_cedula():
    """
    GET endpoint to check if a person is deceased.
    Usage: /check?cedula=102920417
    """
    
    cedula = request.args.get('cedula')

    if not cedula:
        return jsonify({"error": "Missing 'cedula' parameter"}), 400

    result = check_fallecido(cedula)

    if "error" in result:
        return jsonify(result), 500

    return jsonify(result), 200


@app.route('/', methods=['GET'])
def home():
    """
    Home endpoint with usage instructions.
    """
    return jsonify({
        "message": "TSE Cedula Checker API",
        "usage": "GET /check?cedula=<cedula_number>",
        "example": "/check?cedula=102920417"
    }), 200


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8080)

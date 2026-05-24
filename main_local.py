import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, request, jsonify


class PersonNotFound(Exception):
    pass


class MultipleMatches(Exception):
    pass


def _extract_state(soup):
    out = {}
    for name in ('__VIEWSTATE', '__VIEWSTATEGENERATOR', '__EVENTVALIDATION'):
        el = soup.find('input', {'name': name})
        out[name] = el['value'] if el and el.has_attr('value') else ''
    return out


def get_tse_details_html(nombre, apellido1, apellido2):
    """
    Walks the TSE postback flow for a person looked up by name and returns
    the detalle_nacimiento.aspx HTML (which contains lblfallecido).

    Raises PersonNotFound (0 matches) or MultipleMatches (>1 matches).
    """
    session = requests.Session()
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-CR,es;q=0.9,en;q=0.8',
    })

    base_url = "https://servicioselectorales.tse.go.cr/chc"
    search_url = f"{base_url}/consulta_nombres.aspx"
    muestra_url = f"{base_url}/muestra_nombres.aspx"
    result_url = f"{base_url}/resultado_persona.aspx"

    # Step 1: GET search form
    print(f"Step 1: Fetching initial form from {search_url}")
    response = session.get(search_url)
    response.raise_for_status()
    hidden = _extract_state(BeautifulSoup(response.content, 'html.parser'))

    # Step 2: POST name search -> muestra_nombres.aspx
    print(f"Step 2: Searching for {nombre} {apellido1} {apellido2}")
    response = session.post(search_url, data={
        '__LASTFOCUS': '',
        '__EVENTTARGET': '',
        '__EVENTARGUMENT': '',
        **hidden,
        'txtnombre': nombre,
        'txtapellido1': apellido1,
        'txtapellido2': apellido2,
        'btnConsultarNombre': 'Consultar',
        'referencia': '',
        'observacion': '',
    })
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')

    # chk2 is the "select all" checkbox; chk1$N are the per-row checkboxes.
    row_checkboxes = [
        cb for cb in soup.find_all('input', {'type': 'checkbox'})
        if (cb.get('name') or '').startswith('chk1$')
    ]
    print(f"Step 2: Found {len(row_checkboxes)} match(es)")
    if not row_checkboxes:
        raise PersonNotFound(
            f"No person found matching {nombre} {apellido1} {apellido2}"
        )
    if len(row_checkboxes) > 1:
        raise MultipleMatches(
            f"Found {len(row_checkboxes)} people matching "
            f"{nombre} {apellido1} {apellido2}; please be more specific"
        )

    only_checkbox_name = row_checkboxes[0]['name']
    hidden = _extract_state(soup)

    # Step 3: select the single match + click 'Realizar consulta' -> resultado_persona.aspx
    print("Step 3: Selecting match and clicking 'Realizar consulta'")
    response = session.post(muestra_url, data={
        '__LASTFOCUS': '',
        '__EVENTTARGET': '',
        '__EVENTARGUMENT': '',
        **hidden,
        only_checkbox_name: 'on',
        'Button1': 'Realizar consulta',
    })
    response.raise_for_status()
    hidden = _extract_state(BeautifulSoup(response.content, 'html.parser'))

    # Step 4: click 'Ver Más Detalles' -> detalle_nacimiento.aspx
    print("Step 4: Clicking 'Ver Más Detalles' link")
    response = session.post(result_url, data={
        '__EVENTTARGET': 'LinkButton11',
        '__EVENTARGUMENT': '',
        **hidden,
    })
    response.raise_for_status()
    return response.text


def check_fallecido(nombre, apellido1, apellido2):
    """
    Checks if a person is deceased based on their full name.
    """
    try:
        html_content = get_tse_details_html(nombre, apellido1, apellido2)
        soup = BeautifulSoup(html_content, 'html.parser')

        fallecido_span = soup.find('span', {'id': 'lblfallecido'})
        if not fallecido_span:
            return {"error": "Could not find 'lblfallecido' element in HTML",
                    "code": "parse_error"}

        value = fallecido_span.get_text(strip=True).upper()
        cedula_span = soup.find('span', {'id': 'lblcedula'})
        cedula = cedula_span.get_text(strip=True) if cedula_span else None

        if value == "SI":
            return {"fallecido": True, "cedula": cedula}
        if value == "NO":
            return {"fallecido": False, "cedula": cedula}
        return {"error": f"Unknown value for Fallecido/a: {value}",
                "code": "parse_error"}

    except PersonNotFound as e:
        return {"error": str(e), "code": "not_found"}
    except MultipleMatches as e:
        return {"error": str(e), "code": "ambiguous"}
    except Exception as e:
        return {"error": str(e), "code": "unknown"}


app = Flask(__name__)


@app.route('/check', methods=['GET'])
def check_cedula():
    """
    GET /check?nombre=Nora&apellido1=Perez&apellido2=Centeno
    """
    nombre = request.args.get('nombre')
    apellido1 = request.args.get('apellido1')
    apellido2 = request.args.get('apellido2')

    missing = [n for n, v in [
        ('nombre', nombre), ('apellido1', apellido1), ('apellido2', apellido2)
    ] if not v]
    if missing:
        return jsonify({"error": f"Missing required parameter(s): {', '.join(missing)}"}), 400

    result = check_fallecido(nombre, apellido1, apellido2)

    if "error" in result:
        status_by_code = {"not_found": 404, "ambiguous": 409}
        return jsonify(result), status_by_code.get(result.get("code"), 500)

    return jsonify(result), 200


@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "message": "TSE Cedula Checker API",
        "usage": "GET /check?nombre=<nombre>&apellido1=<apellido1>&apellido2=<apellido2>",
        "example": "/check?nombre=Nora&apellido1=Perez&apellido2=Centeno"
    }), 200


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8080)

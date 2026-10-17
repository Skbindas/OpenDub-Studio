"""Official CLI entry point with structured server errors retained for redaction."""
import json
import runpy
import sys


def error_detail(response):
    try:body=response.json()
    except ValueError:return ''
    if not isinstance(body,dict):return ''
    # Do not emit headers, request bodies, cookies, signed URLs or HTML pages.
    selected={key:body[key] for key in ('code','message','error') if key in body}
    return json.dumps(selected,ensure_ascii=False)[:2000] if selected else ''


def main():
    import requests
    original=requests.Response.raise_for_status
    def checked(response):
        try:return original(response)
        except requests.HTTPError as error:
            detail=error_detail(response)
            raise requests.HTTPError(str(error)+('\nProvider response: '+detail if detail else ''),response=response) from None
    requests.Response.raise_for_status=checked
    sys.argv=['kaggle',*sys.argv[1:]]
    runpy.run_module('kaggle',run_name='__main__')


if __name__=='__main__':main()

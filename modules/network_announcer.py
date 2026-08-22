# -*- coding: utf-8 -*-
"""
Module d'annonce réseau locale mDNS / Zeroconf pour Jibayat.
Permet à tous les postes du réseau local d'accéder à l'application
via l'adresse : http://jibayat.local:5050 (sans modifier aucun fichier hosts).
"""

import atexit
import logging
import socket
import threading

logger = logging.getLogger('jibayat.network')

_zc_instance = None
_service_info = None

def get_local_ip():
    """Détecte l'adresse IP locale de la machine sur le réseau."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '127.0.0.1'

def start_network_announcer(port=5050, hostname="jibayat", is_ssl=False):
    """
    Démarre l'annonce mDNS / Zeroconf sur le réseau local.
    Rend disponible : http(s)://<hostname>.local:<port>
    """
    global _zc_instance, _service_info

    def _run():
        global _zc_instance, _service_info
        try:
            from zeroconf import Zeroconf, ServiceInfo

            ip_str = get_local_ip()
            ip_bytes = socket.inet_aton(ip_str)

            proto = "https" if is_ssl else "http"
            srv_type = "_https._tcp.local." if is_ssl else "_http._tcp.local."
            fqdn_server = f"{hostname.lower()}.local."
            service_name = f"Jibayat App ({hostname.upper()}).{srv_type}"

            _service_info = ServiceInfo(
                type_=srv_type,
                name=service_name,
                addresses=[ip_bytes],
                port=port,
                properties={'path': '/'},
                server=fqdn_server
            )

            _zc_instance = Zeroconf()
            _zc_instance.register_service(_service_info)
            display_port = f":{port}" if (port not in (80, 443)) else ""
            logger.info(f"mDNS Annonceur démarré : {proto}://{hostname.lower()}.local{display_port} -> {ip_str}:{port}")

            # Enregistrement du nettoyage automatique à l'arrêt de l'application
            atexit.register(stop_network_announcer)

        except Exception as e:
            logger.warning(f"Impossible de démarrer l'annonceur mDNS Zeroconf : {e}")

    thread = threading.Thread(target=_run, daemon=True, name="mDNS-Announcer")
    thread.start()
    return thread

def stop_network_announcer():
    """Arrête proprement l'annonceur mDNS."""
    global _zc_instance, _service_info
    try:
        if _zc_instance and _service_info:
            _zc_instance.unregister_service(_service_info)
            _zc_instance.close()
            _zc_instance = None
            _service_info = None
    except Exception as e:
        logger.debug(f"Erreur arrêt mDNS : {e}")

#!/bin/sh
# shellcheck source=/dev/null

if [ -z "${LINKY_SOCAT_HOST}" ] && [ -z "${LINKY_SOCAT_FILE}" ]; then
	true
else
	echo "Socat : ${LINKY_SOCAT_FILE} -> ${LINKY_SOCAT_HOST}"
	socat PTY,link="${LINKY_SOCAT_FILE}",raw,user=exporter,group=dialout,mode=777 TCP4:"${LINKY_SOCAT_HOST}",reuseaddr,keepalive,connect-timeout=5,keepcnt=5,keepidle=5,keepintvl=5 &
fi

. "${VIRTUAL_ENV}"/bin/activate
python3 "${SCRIPT}"

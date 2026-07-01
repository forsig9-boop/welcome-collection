import os
import datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom


#Константы

# Формат дат во входном XML (issueDate, applicationDate, nextPaymentDate).
INPUT_DATE_FORMAT = "%Y-%m-%d"

# Границы окна напоминания о предстоящем платеже (включительно)
REMINDER_MIN_DAYS = 5
REMINDER_MAX_DAYS = 7


#Вспомогательные функции

def _get_text(element, tag):
    """Возвращает текст дочернего тега.

    Возвращает None, если родитель отсутствует, тег не найден или пустой.
    Это защищает от падения на пустых контрактах (<contract/>) и
    необязательных полях.
    """
    if element is None:
        return None
    child = element.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _to_float(value, default=0.0):
    """Преобразовывает строку в число. При отсутствии/ошибке вернуть default."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value):
    """Парсит дату формата YYYY-MM-DD. Возвращает datetime.date или None."""
    if not value:
        return None
    try:
        return datetime.datetime.strptime(value, INPUT_DATE_FORMAT).date()
    except ValueError:
        return None


def _add_decision(parent, client_number, sms_type, sms_text, decision_date):
    """Добавляет в дерево ответа один элемент <decision> заданного вида."""
    decision = ET.SubElement(parent, "decision")
    ET.SubElement(decision, "clientNumber").text = client_number or ""
    ET.SubElement(decision, "DecisionType").text = "SMS"
    ET.SubElement(decision, "smsType").text = str(sms_type)
    ET.SubElement(decision, "smsText").text = sms_text
    ET.SubElement(decision, "decisionDate").text = decision_date


#Основная функция

def make_decisions(filepath):
    """Парсит входной XML и сохраняет решения по СМС в response_*.xml.

    :param filepath: путь к входному XML-файлу (например, task1.xml).
    :return: путь к созданному файлу
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    response_root = ET.Element("Response")

    for application in root.findall("Application"):
        client_number = _get_text(application, "clientNumber")

        # Дату заявки храним в двух видах:
        #   raw  — исходная строка YYYY-MM-DD для подстановки в текст СМС
        #          и в поле decisionDate ;
        #   date — объект date для расчёта окна 5-7 дней.
        application_date_raw = _get_text(application, "applicationDate")
        application_date = _parse_date(application_date_raw)

        for contract in application.findall("contract"):
            contract_number = _get_text(contract, "contractNumber")

            if not contract_number:
                continue

            # Сумма просрочки. Сырое значение сохраняем для текста СМС
            # (чтобы не искажать исходное представление числа, напр. 1110.00),
            # числовое — для проверки условия.
            total_overdue_raw = _get_text(contract, "totalOverdue")
            total_overdue = _to_float(total_overdue_raw)

            # по контракту есть просрочка
            # Признак просрочки — положительная сумма totalOverdue.
            # daysOverdue намеренно НЕ используется: контракт может иметь
            # daysOverdue > 0 при нулевой/отсутствующей сумме просрочки
            # (пример — контракт 77777), и слать СМС о просрочке в 0 р нельзя.
            if total_overdue > 0:
                sms_text = (
                    f"На {application_date_raw} по контракту {contract_number} "
                    f"образовалась просрочка в размере {total_overdue_raw} р"
                )
                _add_decision(
                    response_root, client_number, 1, sms_text, application_date_raw
                )
                # Просрочка и напоминание о платеже взаимоисключающи,
                # поэтому к проверке smsType=2 не переходим.
                continue

            #просрочки нет, напоминание о платеже
            next_payment = contract.find("nextPayment")
            next_payment_date = _parse_date(_get_text(next_payment, "nextPaymentDate"))
            next_payment_sum_raw = _get_text(next_payment, "nextPaymentSum")
            next_payment_sum = _to_float(next_payment_sum_raw)
            account_balance = _to_float(_get_text(contract, "accountBalance"))

            # Без даты платежа или даты заявки рассчитать окно нельзя.
            if next_payment_date is None or application_date is None:
                continue

            # Сколько дней до платежа считаем именно от applicationDate
            days_until_payment = (next_payment_date - application_date).days

            in_reminder_window = REMINDER_MIN_DAYS <= days_until_payment <= REMINDER_MAX_DAYS
            not_enough_money = account_balance < next_payment_sum

            if in_reminder_window and not_enough_money:
                sms_text = (
                    f"Напоминаем о предстоящем платеже по контракту "
                    f"{contract_number} в размере {next_payment_sum_raw} р"
                )
                _add_decision(
                    response_root, client_number, 2, sms_text, application_date_raw
                )

    output_path = _save_response(response_root, filepath)
    return output_path


def _save_response(response_root, source_filepath):
    """Сохраняет дерево <Response> в response_<имя>.xml рядом с исходником.

    Файл форматируется с отступами
    """
    # Преобразуем дерево в строку
    rough_bytes = ET.tostring(response_root, encoding="utf-8")
    pretty_xml = minidom.parseString(rough_bytes).toprettyxml(
        indent="    ", encoding="utf-8"
    )

    source_dir = os.path.dirname(os.path.abspath(source_filepath))
    output_name = "response_" + os.path.basename(source_filepath)
    output_path = os.path.join(source_dir, output_name)

    with open(output_path, "wb") as out_file:
        out_file.write(pretty_xml)

    return output_path


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    xml_path = os.path.join(base_dir, "task1.xml")

    result_path = make_decisions(xml_path)
    print(f"Решения сохранены в: {result_path}")
